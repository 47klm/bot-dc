# -*- coding: utf-8 -*-

# =================================================================
# SEKCJA 1: WSZYSTKIE IMPORTY
# =================================================================
import discord
from discord.ext import commands, tasks
from discord import app_commands, ui, ButtonStyle, Interaction, Member, Role, TextChannel, CategoryChannel
import json
import random
import asyncio
import datetime
from typing import Optional
import re
import aiohttp
import os
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import yt_dlp as youtube_dl


# =================================================================
# SEKCJA 2: GŁÓWNA KLASA BOTA I JEJ INSTANCJA
# =================================================================
class ConfigurableBot(commands.Bot):
    """Główna klasa bota, dziedzicząca po commands.Bot dla rozszerzalności."""
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="!unused!", intents=intents)

        self.server_configs = self.load_data('server_configs.json')
        self.warnings_data = self.load_data('warnings.json')
        self.notes_data = self.load_data('notes.json')
        self.levels_data = self.load_data('levels.json')
        self.xp_cooldowns = {}

    def load_data(self, filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f: return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError): return {}

    def save_data(self, data, filename):
        with open(filename, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4)

    def get_config(self, guild_id: int, key: str):
        return self.server_configs.get(str(guild_id), {}).get(key, None)

    def set_config(self, guild_id: int, key: str, value):
        guild_id_str = str(guild_id)
        if guild_id_str not in self.server_configs: self.server_configs[guild_id_str] = {}
        self.server_configs[guild_id_str][key] = value
        self.save_data(self.server_configs, 'server_configs.json')

    async def setup_hook(self):
        """Metoda wywoływana przy starcie bota. Rejestruje komendy i widoki."""
        self.session = aiohttp.ClientSession()

        # Inicjalizacja Coga Muzycznego i jego widoku
        self.music_cog = Music(self)
        self.add_view(MusicView(self, self.music_cog))

        # Inne widoki
        self.add_view(TicketCreateView(self))
        self.add_view(TicketCloseView(self))
        self.add_view(VerificationView(self))

        # Rejestracja wszystkich grup komend
        self.tree.add_command(Konfiguracja(self))
        self.tree.add_command(Moderacja(self))
        self.tree.add_command(Uzytkowe(self))
        self.tree.add_command(Rozrywka(self))
        self.tree.add_command(self.music_cog)

        # Rejestracja samodzielnych komend
        self.tree.add_command(giveaway)
        self.tree.add_command(embed)

        synced = await self.tree.sync()
        print(f"Zsynchronizowano {len(synced)} komend.")

    async def on_ready(self):
        print(f'Zalogowano jako: {self.user.name} | ID: {self.user.id}')
        status_task.start()

bot = ConfigurableBot()


# =================================================================
# SEKCJA 3: ZADANIA I EVENTY
# =================================================================
@tasks.loop(seconds=30)
async def status_task():
    await bot.change_presence(activity=discord.Game(f"na {len(bot.guilds)} serwerach"))

def parse_duration(duration_str: str) -> Optional[datetime.timedelta]:
    matches = re.findall(r'(\d+)([dhms])', duration_str.lower())
    if not matches: return None
    delta_args = {'days': 0, 'hours': 0, 'minutes': 0, 'seconds': 0}
    time_map = {'d': 'days', 'h': 'hours', 'm': 'minutes', 's': 'seconds'}
    for value, unit in matches: delta_args[time_map[unit]] += int(value)
    return datetime.timedelta(**delta_args)

@bot.event
async def on_member_join(member: Member):
    guild = member.guild
    welcome_channel_id = bot.get_config(guild.id, 'welcome_channel_id')
    if welcome_channel_id and (channel := guild.get_channel(welcome_channel_id)):
        embed = discord.Embed(title=f"Witaj na serwerze {guild.name}!", description=f"Cieszymy się, że dołączyłeś/aś, {member.mention}!", color=discord.Color.green())
        embed.set_thumbnail(url=member.display_avatar.url)
        await channel.send(embed=embed)
    auto_role_id = bot.get_config(guild.id, 'auto_role_id')
    if auto_role_id and (role := guild.get_role(auto_role_id)):
        try: await member.add_roles(role)
        except discord.Forbidden: print(f"Błąd uprawnień: Nie mogę nadać roli '{role.name}' na serwerze '{guild.name}'.")

@bot.event
async def on_member_remove(member: Member):
    goodbye_channel_id = bot.get_config(member.guild.id, 'goodbye_channel_id')
    if goodbye_channel_id and (channel := member.guild.get_channel(goodbye_channel_id)):
        embed = discord.Embed(title="Użytkownik opuścił serwer", description=f"Żegnaj, **{member.display_name}**.", color=discord.Color.red())
        embed.set_thumbnail(url=member.display_avatar.url)
        await channel.send(embed=embed)

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild: return
    guild_id, user_id = str(message.guild.id), str(message.author.id)
    cooldown_key = f"{guild_id}-{user_id}"
    if cooldown_key in bot.xp_cooldowns and (datetime.datetime.utcnow() - bot.xp_cooldowns[cooldown_key]).total_seconds() < 60: return
    bot.xp_cooldowns[cooldown_key] = datetime.datetime.utcnow()
    if guild_id not in bot.levels_data: bot.levels_data[guild_id] = {}
    if user_id not in bot.levels_data[guild_id]: bot.levels_data[guild_id][user_id] = {'xp': 0, 'level': 1}
    bot.levels_data[guild_id][user_id]['xp'] += random.randint(15, 25)
    current_level = bot.levels_data[guild_id][user_id]['level']
    xp_needed = int(5 * (current_level ** 2) + 50 * current_level + 100)
    if bot.levels_data[guild_id][user_id]['xp'] >= xp_needed:
        bot.levels_data[guild_id][user_id]['level'] += 1
        new_level = bot.levels_data[guild_id][user_id]['level']
        try: await message.channel.send(f"🎉 Gratulacje, {message.author.mention}! Osiągnąłeś **{new_level}** poziom!", delete_after=15)
        except discord.Forbidden: pass
    bot.save_data(bot.levels_data, 'levels.json')

# =================================================================
# SEKCJA 4: WSZYSTKIE KLASY WIDOKÓW I KOMEND
# =================================================================
class VerificationView(ui.View):
    def __init__(self, bot_instance): super().__init__(timeout=None); self.bot = bot_instance
    @ui.button(label="✅ Zweryfikuj się", style=ButtonStyle.success, custom_id="verify_button")
    async def verify_button(self, interaction: Interaction, button: ui.Button):
        role_id = self.bot.get_config(interaction.guild.id, 'verification_role_id')
        if not role_id or not (role := interaction.guild.get_role(role_id)): return await interaction.response.send_message("Błąd: Rola weryfikacyjna nie jest skonfigurowana.", ephemeral=True)
        if role in interaction.user.roles: return await interaction.response.send_message("Jesteś już zweryfikowany.", ephemeral=True)
        try: await interaction.user.add_roles(role); await interaction.response.send_message("Pomyślnie Cię zweryfikowano!", ephemeral=True)
        except discord.Forbidden: await interaction.response.send_message("Błąd: Nie mam uprawnień, by nadać Ci tę rolę.", ephemeral=True)

class TicketCreateView(ui.View):
    def __init__(self, bot_instance): super().__init__(timeout=None); self.bot = bot_instance
    @ui.button(label="✉️ Utwórz Ticket", style=ButtonStyle.primary, custom_id="create_ticket_button")
    async def create_ticket(self, interaction: Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        category_id = self.bot.get_config(interaction.guild.id, 'ticket_category_id')
        staff_role_id = self.bot.get_config(interaction.guild.id, 'ticket_staff_role_id')
        if not category_id or not staff_role_id: return await interaction.followup.send("System ticketów nie jest skonfigurowany.", ephemeral=True)
        category = interaction.guild.get_channel(category_id)
        staff_role = interaction.guild.get_role(staff_role_id)
        overwrites = {interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False), interaction.user: discord.PermissionOverwrite(view_channel=True), staff_role: discord.PermissionOverwrite(view_channel=True, manage_channels=True)}
        channel = await category.create_text_channel(name=f"ticket-{interaction.user.name}", overwrites=overwrites)
        embed = discord.Embed(title="Ticket otwarty!", description=f"Witaj {interaction.user.mention}! Opisz swój problem, a ktoś z {staff_role.mention} wkrótce się z Tobą skontaktuje.", color=0x2ecc71)
        await channel.send(content=f"{interaction.user.mention} {staff_role.mention}", embed=embed, view=TicketCloseView(self.bot))
        await interaction.followup.send(f"Twój ticket został otwarty: {channel.mention}", ephemeral=True)

class TicketCloseView(ui.View):
    def __init__(self, bot_instance): super().__init__(timeout=None); self.bot = bot_instance
    @ui.button(label="🔒 Zamknij Ticket", style=ButtonStyle.danger, custom_id="close_ticket_button")
    async def close_ticket(self, interaction: Interaction, button: ui.Button):
        await interaction.response.send_message("Kanał zostanie usunięty za 5 sekund...")
        await asyncio.sleep(5)
        await interaction.channel.delete(reason=f"Ticket zamknięty przez {interaction.user.name}")

class GiveawayView(ui.View):
    def __init__(self, bot_instance, end_time: datetime.datetime, prize: str):
        super().__init__(timeout=(end_time - datetime.datetime.utcnow()).total_seconds()); self.bot = bot_instance; self.prize = prize; self.participants = set()
    @ui.button(label="🎉 Dołącz", style=ButtonStyle.success, custom_id="join_giveaway_button")
    async def join_giveaway(self, interaction: Interaction, button: ui.Button):
        if interaction.user.id in self.participants: return await interaction.response.send_message("Już bierzesz udział!", ephemeral=True)
        self.participants.add(interaction.user.id); await interaction.response.send_message("Pomyślnie dołączyłeś/aś do konkursu!", ephemeral=True)
    async def on_timeout(self):
        for item in self.children: item.disabled = True
        try:
            message = await self.message.channel.fetch_message(self.message.id)
            original_embed = message.embeds[0]
        except (discord.NotFound, AttributeError):
            print("Nie udało się pobrać oryginalnej wiadomości konkursu (prawdopodobnie została usunięta).")
            return

        original_embed.color = discord.Color.greyple()
        winner_id = random.choice(list(self.participants)) if self.participants else None

        if winner_id and (winner_user := self.bot.get_user(winner_id)):
            end_text = f"Zwycięzca: {winner_user.mention}"
            await message.channel.send(f"🎉 Gratulacje {winner_user.mention}! Wygrałeś/aś **{self.prize}**!")
        else:
            end_text = "Zwycięzca: Brak (nikt nie wziął udziału)"

        original_embed.description += f"\n\n**Zakończono!**\n{end_text}"
        await message.edit(embed=original_embed, view=self)

class Konfiguracja(app_commands.Group):
    def __init__(self, bot_instance): super().__init__(name="konfiguracja"); self.bot = bot_instance
    @app_commands.command(name="powitania", description="Ustaw kanał powitań.")
    @app_commands.checks.has_permissions(administrator=True)
    async def powitania(self, interaction: Interaction, kanał: TextChannel):
        self.bot.set_config(interaction.guild.id, 'welcome_channel_id', kanał.id); await interaction.response.send_message(f"✅ Ustawiono kanał powitań na {kanał.mention}.", ephemeral=True)
    @app_commands.command(name="pozegnania", description="Ustaw kanał pożegnań.")
    @app_commands.checks.has_permissions(administrator=True)
    async def pozegnania(self, interaction: Interaction, kanał: TextChannel):
        self.bot.set_config(interaction.guild.id, 'goodbye_channel_id', kanał.id); await interaction.response.send_message(f"✅ Ustawiono kanał pożegnań na {kanał.mention}.", ephemeral=True)
    @app_commands.command(name="auto-rola", description="Ustaw rolę nadawaną po wejściu.")
    @app_commands.checks.has_permissions(administrator=True)
    async def auto_rola(self, interaction: Interaction, rola: Role):
        self.bot.set_config(interaction.guild.id, 'auto_role_id', rola.id); await interaction.response.send_message(f"✅ Ustawiono auto-rolę na {rola.mention}.", ephemeral=True)
    @app_commands.command(name="weryfikacja", description="Tworzy panel weryfikacyjny.")
    @app_commands.checks.has_permissions(administrator=True)
    async def weryfikacja(self, interaction: Interaction, kanał: TextChannel, rola: Role, tresc_wiadomosci: str):
        self.bot.set_config(interaction.guild.id, 'verification_role_id', rola.id); embed = discord.Embed(title="✅ Weryfikacja", description=tresc_wiadomosci, color=discord.Color.gold()); await kanał.send(embed=embed, view=VerificationView(self.bot)); await interaction.response.send_message(f"✅ Panel weryfikacyjny utworzono na {kanał.mention}.", ephemeral=True)
    @app_commands.command(name="tickety", description="Konfiguruje system ticketów.")
    @app_commands.checks.has_permissions(administrator=True)
    async def tickety(self, interaction: Interaction, kategoria: CategoryChannel, rola_staffu: Role, kanał_panelu: TextChannel):
        self.bot.set_config(interaction.guild.id, 'ticket_category_id', kategoria.id); self.bot.set_config(interaction.guild.id, 'ticket_staff_role_id', rola_staffu.id); embed = discord.Embed(title="Wsparcie Techniczne", description="Kliknij przycisk, aby otworzyć prywatny kanał z administracją.", color=discord.Color.blue()); await kanał_panelu.send(embed=embed, view=TicketCreateView(self.bot)); await interaction.response.send_message(f"✅ Panel ticketów utworzono na {kanał_panelu.mention}.", ephemeral=True)

class Moderacja(app_commands.Group):
    def __init__(self, bot_instance): super().__init__(name="moderacja"); self.bot = bot_instance
    @app_commands.command(name="ban", description="Banuje użytkownika.")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(self, interaction: Interaction, uzytkownik: Member, powod: Optional[str] = "Brak powodu"):
        if uzytkownik.top_role >= interaction.user.top_role and interaction.guild.owner != interaction.user: return await interaction.response.send_message("Nie możesz banować osób z wyższą/taką samą rolą!", ephemeral=True)
        await uzytkownik.ban(reason=f"{interaction.user.name}: {powod}"); await interaction.response.send_message(f"✅ **{uzytkownik.display_name}** został zbanowany.", ephemeral=True)
    @app_commands.command(name="unban", description="Odbanowuje użytkownika po ID.")
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban(self, interaction: Interaction, user_id: str):
        try: user = discord.Object(id=int(user_id)); await interaction.guild.unban(user); await interaction.response.send_message(f"✅ Użytkownik o ID `{user_id}` został odbanowany.", ephemeral=True)
        except (ValueError, discord.NotFound): await interaction.response.send_message("Nieprawidłowe ID lub użytkownik nie jest zbanowany.", ephemeral=True)
    @app_commands.command(name="kick", description="Wyrzuca użytkownika.")
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick(self, interaction: Interaction, uzytkownik: Member, powod: Optional[str] = "Brak powodu"):
        await uzytkownik.kick(reason=f"{interaction.user.name}: {powod}"); await interaction.response.send_message(f"✅ **{uzytkownik.display_name}** został wyrzucony.", ephemeral=True)
    @app_commands.command(name="mute", description="Wycisza użytkownika (max 28 dni).")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def mute(self, interaction: Interaction, uzytkownik: Member, czas_trwania: str, powod: Optional[str] = "Brak powodu"):
        if uzytkownik.top_role >= interaction.guild.me.top_role:
            return await interaction.response.send_message("Błąd: Nie mogę wyciszyć kogoś z rolą równą lub wyższą od mojej.", ephemeral=True)
        duration = parse_duration(czas_trwania)
        if not duration or duration.days > 28:
            return await interaction.response.send_message("Nieprawidłowy format czasu lub czas jest dłuższy niż 28 dni!", ephemeral=True)
        try:
            await uzytkownik.timeout(duration, reason=powod)
            await interaction.response.send_message(f"🔇 **{uzytkownik.display_name}** został wyciszony na `{czas_trwania}`.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("Błąd: Nie mam uprawnień do wyciszania użytkowników na tym serwerze.", ephemeral=True)
    @app_commands.command(name="unmute", description="Zdejmuje wyciszenie.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def unmute(self, interaction: Interaction, uzytkownik: Member):
        if not uzytkownik.is_timed_out():
            return await interaction.response.send_message("Ten użytkownik nie jest wyciszony.", ephemeral=True)
        try:
            await uzytkownik.timeout(None, reason=f"Odciszony przez {interaction.user.name}")
            await interaction.response.send_message(f"🔊 Zdjęto wyciszenie z **{uzytkownik.display_name}**.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("Błąd: Nie mam uprawnień, by zdejmować wyciszenia.", ephemeral=True)
    @app_commands.command(name="clear", description="Czyści wiadomości.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear(self, interaction: Interaction, liczba: app_commands.Range[int, 1, 100]):
        await interaction.response.defer(ephemeral=True, thinking=True)
        deleted = await interaction.channel.purge(limit=liczba)
        await interaction.followup.send(f"✅ Usunięto `{len(deleted)}` wiadomości.")
    @app_commands.command(name="warn", description="Daje ostrzeżenie.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def warn(self, interaction: Interaction, uzytkownik: Member, powod: str):
        guild_id, user_id = str(interaction.guild.id), str(uzytkownik.id)
        if guild_id not in self.bot.warnings_data: self.bot.warnings_data[guild_id] = {}
        if user_id not in self.bot.warnings_data[guild_id]: self.bot.warnings_data[guild_id][user_id] = []
        self.bot.warnings_data[guild_id][user_id].append({'reason': powod, 'moderator_id': interaction.user.id, 'timestamp': datetime.datetime.utcnow().isoformat()}); self.bot.save_data(self.bot.warnings_data, 'warnings.json')
        await interaction.response.send_message(f"⚠️ **{uzytkownik.display_name}** otrzymał ostrzeżenie (łącznie: {len(self.bot.warnings_data[guild_id][user_id])}).")
    @app_commands.command(name="del-warn", description="Usuwa ostrzeżenie.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def del_warn(self, interaction: Interaction, uzytkownik: Member, numer_warna: int):
        user_warns = self.bot.warnings_data.get(str(interaction.guild.id), {}).get(str(uzytkownik.id), [])
        if 1 <= numer_warna <= len(user_warns): user_warns.pop(numer_warna - 1); self.bot.save_data(self.bot.warnings_data, 'warnings.json'); await interaction.response.send_message(f"✅ Usunięto ostrzeżenie nr `{numer_warna}`.", ephemeral=True)
        else: await interaction.response.send_message("Nieprawidłowy numer ostrzeżenia.", ephemeral=True)
    @app_commands.command(name="history", description="Pokazuje historię ostrzeżeń.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def history(self, interaction: Interaction, uzytkownik: Member):
        warns = self.bot.warnings_data.get(str(interaction.guild.id), {}).get(str(uzytkownik.id), []); embed = discord.Embed(title=f"Historia - {uzytkownik.display_name}", color=uzytkownik.color)
        if warns: text = "".join(f"**{i}.** <t:{int(discord.utils.parse_time(w['timestamp']).timestamp())}:D> - `{w['reason']}`\n" for i, w in enumerate(warns, 1)); embed.add_field(name=f"Ostrzeżenia ({len(warns)})", value=text)
        else: embed.add_field(name="Ostrzeżenia", value="Brak.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

class Uzytkowe(app_commands.Group):
    def __init__(self, bot_instance): super().__init__(name="uzytkowe"); self.bot = bot_instance
    @app_commands.command(name="info", description="Wyświetla informacje o serwerze.")
    async def info(self, interaction: Interaction):
        g = interaction.guild; embed = discord.Embed(title=f"Informacje o serwerze {g.name}", color=discord.Color.blue()); embed.set_thumbnail(url=g.icon.url if g.icon else None)
        embed.add_field(name="👑 Właściciel", value=g.owner.mention).add_field(name="👥 Użytkownicy", value=g.member_count).add_field(name="📅 Utworzono", value=f"<t:{int(g.created_at.timestamp())}:D>"); await interaction.response.send_message(embed=embed)
    @app_commands.command(name="avatar", description="Wyświetla avatar użytkownika.")
    async def avatar(self, interaction: Interaction, uzytkownik: Optional[Member] = None):
        target = uzytkownik or interaction.user; embed = discord.Embed(title=f"Avatar - {target.display_name}", color=target.color); embed.set_image(url=target.display_avatar.url); await interaction.response.send_message(embed=embed)
    @app_commands.command(name="ping", description="Sprawdza opóźnienie bota.")
    async def ping(self, interaction: Interaction): await interaction.response.send_message(f"Pong! 🏓 `{round(self.bot.latency * 1000)}ms`")
    @app_commands.command(name="level", description="Sprawdza Twój poziom lub innej osoby.")
    async def level(self, interaction: Interaction, uzytkownik: Optional[Member] = None):
        target = uzytkownik or interaction.user
        user_data = self.bot.levels_data.get(str(interaction.guild.id), {}).get(str(target.id), None)
        if not user_data: return await interaction.response.send_message(f"**{target.display_name}** nie ma jeszcze poziomu.", ephemeral=True)
        lvl, xp = user_data['level'], user_data['xp']; xp_needed = int(5 * (lvl ** 2) + 50 * lvl + 100)
        progress = int((xp / xp_needed) * 20) if xp_needed > 0 else 0; progress_bar = '🟩' * progress + '⬛' * (20 - progress)
        embed = discord.Embed(title=f"Poziom - {target.display_name}", color=target.color); embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Poziom", value=f"**{lvl}**").add_field(name="XP", value=f"`{xp}/{xp_needed}`").add_field(name="Postęp", value=f"[{progress_bar}]", inline=False)
        await interaction.response.send_message(embed=embed)
    @app_commands.command(name="leaderboard", description="Wyświetla ranking 10 najlepszych użytkowników.")
    async def leaderboard(self, interaction: Interaction):
        guild_levels = self.bot.levels_data.get(str(interaction.guild.id), {})
        if not guild_levels: return await interaction.response.send_message("Na tym serwerze nikt jeszcze nie zdobył poziomu!", ephemeral=True)
        sorted_users = sorted(guild_levels.items(), key=lambda item: (item[1].get('level', 0), item[1].get('xp', 0)), reverse=True)
        embed = discord.Embed(title=f"🏆 Ranking serwera {interaction.guild.name}", color=discord.Color.gold())
        description = "".join(f"**{i}.** <@{user_id}> - Poziom: **{data.get('level', 0)}** (XP: {data.get('xp', 0)})\n" for i, (user_id, data) in enumerate(sorted_users[:10], 1))
        embed.description = description; await interaction.response.send_message(embed=embed)
    @app_commands.command(name="powiedz", description="Bot powtarza wiadomość.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def powiedz(self, interaction: Interaction, wiadomosc: str):
        await interaction.channel.send(wiadomosc); await interaction.response.send_message("Wysłano!", ephemeral=True, delete_after=3)

class Rozrywka(app_commands.Group):
    def __init__(self, bot_instance): super().__init__(name="fun"); self.bot = bot_instance
    @app_commands.command(name="witaj", description="Przywitaj się z botem.")
    async def witaj(self, interaction: Interaction): await interaction.response.send_message(f"Cześć, {interaction.user.mention}!")
    @app_commands.command(name="8ball", description="Magiczna kula odpowie na Twoje pytanie.")
    async def eight_ball(self, interaction: Interaction, pytanie: str):
        odpowiedzi = ["To pewne.", "Zdecydowanie tak.", "Moja odpowiedź brzmi nie.", "Bardzo wątpliwe.", "Zapytaj ponownie."]; await interaction.response.send_message(f"> {pytanie}\n🎱 **Odpowiedź:** {random.choice(odpowiedzi)}")
    @app_commands.command(name="ship", description="Sprawdza miłość między dwoma osobami.")
    async def ship(self, interaction: Interaction, osoba1: Member, osoba2: Member):
        love_percent = random.randint(0, 100)
        if love_percent <= 20: emoji, comment = "💔", "Raczej nic z tego nie będzie..."
        elif love_percent <= 50: emoji, comment = "🤔", "Jest jakaś szansa, ale nie za duża."
        elif love_percent <= 80: emoji, comment = "😊", "Całkiem dobrze to wygląda! Jest potencjał."
        else: emoji, comment = "💖", "To musi być prawdziwa miłość! Idealne dopasowanie!"
        embed = discord.Embed(title="💕 Miernik Miłości 💕", description=f"Sprawdzam dopasowanie między **{osoba1.display_name}** a **{osoba2.display_name}**...", color=discord.Color.magenta())
        embed.add_field(name="Wynik", value=f"## `{love_percent}%` {emoji}")
        embed.set_footer(text=comment)
        await interaction.response.send_message(embed=embed)
    @app_commands.command(name="meme", description="Wyświetla losowego mema.")
    async def meme(self, interaction: Interaction):
        await interaction.response.defer(thinking=True)
        async with self.bot.session.get("https://meme-api.com/gimme") as r:
            if r.status == 200: data = await r.json(); embed = discord.Embed(title=data['title'], url=data['postLink'], color=0xff4500); embed.set_image(url=data['url']); await interaction.followup.send(embed=embed)
            else: await interaction.followup.send("Nie udało się pobrać mema.", ephemeral=True)
    @app_commands.command(name="hug", description="Przytul kogoś.")
    async def hug(self, interaction: Interaction, uzytkownik: Member): await send_interaction_gif(interaction, uzytkownik, "mocno przytula", ["https://media1.tenor.com/m/p1GGOs0i2dkAAAAC/hug-love.gif"], discord.Color.purple())
    @app_commands.command(name="pat", description="Pogłaszcz kogoś.")
    async def pat(self, interaction: Interaction, uzytkownik: Member): await send_interaction_gif(interaction, uzytkownik, "głaszcze", ["https://media1.tenor.com/m/D212_d8G9HAAAAAC/anime-pat.gif"], discord.Color.light_grey())
    @app_commands.command(name="slap", description="Daj komuś z liścia.")
    async def slap(self, interaction: Interaction, uzytkownik: Member): await send_interaction_gif(interaction, uzytkownik, "daje z liścia", ["https://media1.tenor.com/m/VEe-d_iF0iAAAAAC/anime-slap-mad.gif"], discord.Color.dark_red())

async def send_interaction_gif(interaction: Interaction, uzytkownik: Member, action_text: str, gifs: list, color: discord.Color):
    if uzytkownik == interaction.user: return await interaction.response.send_message("Nie możesz tego zrobić samemu sobie!", ephemeral=True)
    embed = discord.Embed(description=f"{interaction.user.mention} {action_text} {uzytkownik.mention}!", color=color); embed.set_image(url=random.choice(gifs)); await interaction.response.send_message(embed=embed)

@app_commands.command(name="giveaway", description="Rozpoczyna konkurs na serwerze.")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway(interaction: Interaction, czas_trwania: str, nagroda: str, kanał: Optional[TextChannel] = None):
    channel = kanał or interaction.channel
    duration = parse_duration(czas_trwania)
    if not duration: return await interaction.response.send_message("Nieprawidłowy format czasu.", ephemeral=True)
    end_time = datetime.datetime.utcnow() + duration
    embed = discord.Embed(title="🎉 Nowy Konkurs! 🎉", color=discord.Color.magenta())
    embed.add_field(name="Nagroda", value=f"**{nagroda}**", inline=False).add_field(name="Koniec za", value=f"<t:{int(end_time.timestamp())}:R>", inline=False)
    view = GiveawayView(bot, end_time, nagroda)
    message = await channel.send(embed=embed, view=view)
    view.message = message
    await interaction.response.send_message(f"Konkurs rozpoczęto na {channel.mention}!", ephemeral=True)

class EmbedBuilderModal(ui.Modal):
    embed_title = ui.TextInput(label="Tytuł", style=discord.TextStyle.short, required=True, max_length=256)
    embed_description = ui.TextInput(label="Opis", style=discord.TextStyle.long, required=True, max_length=2000)
    embed_color = ui.TextInput(label="Kolor (HEX, np. #FF0000)", style=discord.TextStyle.short, required=False, max_length=7, placeholder="#000000")
    def __init__(self, parent_view: ui.View):
        super().__init__(title="Kreator Głównej Treści Embeda")
        self.parent_view = parent_view
    async def on_submit(self, interaction: Interaction):
        embed = self.parent_view.embed
        embed.title = self.embed_title.value
        embed.description = self.embed_description.value
        color_str = self.embed_color.value
        if color_str and re.match(r'^#(?:[0-9a-fA-F]{3}){1,2}$', color_str):
            embed.color = discord.Color(int(color_str[1:], 16))
        else:
            embed.color = discord.Color.default()
        await interaction.response.edit_message(embed=embed, view=self.parent_view)

class EmbedFieldModal(ui.Modal):
    field_name = ui.TextInput(label="Nazwa Pola", style=discord.TextStyle.short, required=True, max_length=256)
    field_value = ui.TextInput(label="Wartość Pola", style=discord.TextStyle.long, required=True, max_length=1024)
    field_inline = ui.TextInput(label="W jednej linii? (Tak/Nie)", style=discord.TextStyle.short, required=False, max_length=3, placeholder="Tak")
    def __init__(self, parent_view: ui.View):
        super().__init__(title="Dodaj Nowe Pole")
        self.parent_view = parent_view
    async def on_submit(self, interaction: Interaction):
        embed = self.parent_view.embed
        if len(embed.fields) >= 25:
            return await interaction.response.send_message("Osiągnięto limit 25 pól w embedzie!", ephemeral=True, delete_after=10)
        inline = self.field_inline.value.lower() in ['tak', 'yes', 'true', 't']
        embed.add_field(name=self.field_name.value, value=self.field_value.value, inline=inline)
        await interaction.response.edit_message(embed=embed, view=self.parent_view)

class EmbedBuilderView(ui.View):
    def __init__(self, bot_instance, original_interaction: Interaction):
        super().__init__(timeout=300)
        self.bot = bot_instance
        self.original_interaction = original_interaction
        self.embed = discord.Embed(title="Nowy Embed", description="Kliknij przyciski, by go edytować.")
    async def on_timeout(self):
        for item in self.children: item.disabled = True
        try: await self.original_interaction.edit_original_response(content="Czas na edycję minął.", view=self)
        except discord.NotFound: pass
    @ui.button(label="Edytuj Tytuł/Opis", style=ButtonStyle.primary, row=0)
    async def edit_core_button(self, interaction: Interaction, button: ui.Button):
        await interaction.response.send_modal(EmbedBuilderModal(parent_view=self))
    @ui.button(label="Dodaj Pole", style=ButtonStyle.secondary, row=0)
    async def add_field_button(self, interaction: Interaction, button: ui.Button):
        await interaction.response.send_modal(EmbedFieldModal(parent_view=self))
    @ui.button(label="Wyślij Embed", style=ButtonStyle.success, row=1)
    async def send_embed_button(self, interaction: Interaction, button: ui.Button):
        try:
            await interaction.channel.send(embed=self.embed)
            await interaction.response.send_message("Embed został wysłany!", ephemeral=True, delete_after=5)
            self.stop()
            await self.original_interaction.edit_original_response(content="Embed utworzony i wysłany.", view=None, embed=self.embed)
        except Exception as e:
            await interaction.response.send_message(f"Wystąpił błąd przy wysyłaniu: {e}", ephemeral=True)
    @ui.button(label="Anuluj", style=ButtonStyle.danger, row=1)
    async def cancel_button(self, interaction: Interaction, button: ui.Button):
        self.stop()
        await interaction.response.edit_message(content="Anulowano tworzenie embeda.", view=None, embed=None)

@app_commands.command(name="embed", description="Tworzy wiadomość embed za pomocą kreatora.")
@app_commands.checks.has_permissions(manage_messages=True)
async def embed(interaction: Interaction):
    view = EmbedBuilderView(bot, interaction)
    await interaction.response.send_message(
        content="Użyj przycisków poniżej, aby stworzyć i wysłać swój embed.",
        embed=view.embed,
        view=view,
        ephemeral=True
    )

# --- NOWE FUNKCJE: SYSTEM MUZYCZNY (OSTATECZNA WERSJA) ---

class MusicView(ui.View):
    def __init__(self, bot_instance, music_cog):
        super().__init__(timeout=None)
        self.bot = bot_instance
        self.music = music_cog
    async def interaction_check(self, interaction: Interaction) -> bool:
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("Musisz być na kanale głosowym, aby używać przycisków!", ephemeral=True); return False
        if not (vc := interaction.guild.voice_client) or vc.channel != interaction.user.voice.channel:
            await interaction.response.send_message("Musisz być na tym samym kanale co bot!", ephemeral=True); return False
        return True
    @ui.button(label="⏯️", style=ButtonStyle.primary, custom_id="music_play_pause")
    async def play_pause(self, interaction: Interaction, button: ui.Button):
        vc = interaction.guild.voice_client
        if vc.is_paused(): vc.resume(); await interaction.response.send_message("Wznowiono.", ephemeral=True, delete_after=3)
        elif vc.is_playing(): vc.pause(); await interaction.response.send_message("Zapauzowano.", ephemeral=True, delete_after=3)
    @ui.button(label="⏹️", style=ButtonStyle.danger, custom_id="music_stop")
    async def stop(self, interaction: Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True); await self.music.stop(interaction)
    @ui.button(label="⏭️", style=ButtonStyle.secondary, custom_id="music_skip")
    async def skip(self, interaction: Interaction, button: ui.Button):
        await interaction.response.send_message("Pominięto utwór.", ephemeral=True); await self.music.skip(interaction)
    @ui.button(label="🔁", style=ButtonStyle.secondary, custom_id="music_loop")
    async def loop(self, interaction: Interaction, button: ui.Button):
        state = self.music.toggle_loop(interaction.guild.id); status = "włączona" if state else "wyłączona"
        await interaction.response.send_message(f"Pętla utworu: **{status}**.", ephemeral=True)
    @ui.button(label="🔀", style=ButtonStyle.secondary, custom_id="music_shuffle")
    async def shuffle(self, interaction: Interaction, button: ui.Button):
        if self.music.shuffle_queue(interaction.guild.id): await interaction.response.send_message("Kolejka została przetasowana.", ephemeral=True)
        else: await interaction.response.send_message("Kolejka jest pusta.", ephemeral=True)

class Music(app_commands.Group):
    def __init__(self, bot_instance: ConfigurableBot):
        super().__init__(name="music")
        self.bot = bot_instance
        self.queues = {}
        self.loop_states = {}
        self.now_playing_message = {}
        self.YDL_OPTIONS = {'format': 'bestaudio', 'noplaylist': True, 'quiet': True, 'default_search': 'ytsearch1'}
        self.FFMPEG_OPTIONS = {'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5', 'options': '-vn'}
        try:
            self.sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=os.getenv("SPOTIPY_CLIENT_ID"), client_secret=os.getenv("SPOTIPY_CLIENT_SECRET")))
        except Exception as e:
            print(f"Błąd inicjalizacji Spotify: {e}."); self.sp = None

    async def teardown(self, guild_id: int):
        if message := self.now_playing_message.pop(guild_id, None):
            try: await message.delete()
            except discord.HTTPException: pass
        if vc := self.bot.get_guild(guild_id).voice_client:
            await vc.disconnect()
        if guild_id in self.queues: self.queues[guild_id] = []
        if guild_id in self.loop_states: self.loop_states[guild_id] = False

    def get_queue(self, guild_id: int): return self.queues.get(guild_id, [])
    def is_looping(self, guild_id: int) -> bool: return self.loop_states.get(guild_id, False)
    def toggle_loop(self, guild_id: int) -> bool: self.loop_states[guild_id] = not self.is_looping(guild_id); return self.loop_states[guild_id]
    def shuffle_queue(self, guild_id: int) -> bool:
        queue = self.get_queue(guild_id)
        if not queue: return False
        random.shuffle(queue); return True

    async def play_next(self, interaction: Interaction):
        guild_id = interaction.guild.id
        vc = interaction.guild.voice_client
        if not vc or not vc.is_connected():
            return await self.teardown(guild_id)

        if message := self.now_playing_message.pop(guild_id, None):
            try: await message.delete()
            except discord.HTTPException: pass

        queue = self.get_queue(guild_id)
        song_info = None
        if self.is_looping(guild_id) and vc.source:
            song_info = vc.source.original_song_info
        elif queue:
            song_info = queue.pop(0)
        else:
            await interaction.channel.send("Koniec kolejki, rozłączam się.", delete_after=15)
            return await self.teardown(guild_id)

        try:
            source = discord.FFmpegPCMAudio(song_info['url'], **self.FFMPEG_OPTIONS)
            source = discord.PCMVolumeTransformer(source, volume=0.5)
            source.original_song_info = song_info
            vc.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(self.play_next(interaction), self.bot.loop) if not e else print(f"Player error: {e}"))

            embed = discord.Embed(title="🎵 Teraz odtwarzane", description=f"**[{song_info.get('title', 'Brak tytułu')}]({song_info.get('url')})**", color=discord.Color.green())
            if thumbnail := song_info.get('thumbnail'): embed.set_thumbnail(url=thumbnail)
            self.now_playing_message[guild_id] = await interaction.channel.send(embed=embed, view=MusicView(self.bot, self))
        except Exception as e:
            await interaction.channel.send(f"Błąd odtwarzania `{song_info.get('title')}`: {e}")
            await self.play_next(interaction)

    async def search_song_on_yt(self, query: str):
        loop = self.bot.loop
        search_suffixes = ["", " lyrics", " audio"]

        for suffix in search_suffixes:
            try:
                search_query = f"ytsearch1:{query}{suffix}"
                data = await loop.run_in_executor(None, lambda: youtube_dl.YoutubeDL(self.YDL_OPTIONS).extract_info(search_query, download=False))
                if 'entries' in data and data['entries']:
                    entry = data['entries'][0]
                    return {'url': entry['url'], 'title': entry.get('title', 'Brak tytułu'), 'thumbnail': entry.get('thumbnail')}, None
            except Exception:
                print(f"Wyszukiwanie dla '{query}{suffix}' nie powiodło się, próbuje dalej...")
                continue

        return None, f"Nie udało mi się znaleźć grywalnej wersji dla: `{query}`."

    @app_commands.command(name="play", description="Odtwarza piosenkę lub playlistę.")
    async def play(self, interaction: Interaction, query: str):
        if not interaction.user.voice:
            return await interaction.response.send_message("Musisz być na kanale głosowym!", ephemeral=True)
        await interaction.response.defer(thinking=True)

        vc = interaction.guild.voice_client
        if not vc: vc = await interaction.user.voice.channel.connect()

        guild_id = interaction.guild.id
        if guild_id not in self.queues: self.queues[guild_id] = []

        search_queries = []
        # POPRAWKA: Niezawodne wykrywanie linków Spotify
        if self.sp and "open.spotify.com" in query:
            if "track" in query:
                try: search_queries.append(f"{self.sp.track(query)['name']} {self.sp.track(query)['artists'][0]['name']}")
                except Exception as e: return await interaction.followup.send(f"Błąd przetwarzania utworu Spotify: {e}")
            elif "playlist" in query:
                try: search_queries = [f"{item['track']['name']} {item['track']['artists'][0]['name']}" for item in self.sp.playlist_items(query)['items'] if item and item.get('track')]
                except Exception as e: return await interaction.followup.send(f"Błąd przetwarzania playlisty Spotify: {e}")
        else:
            search_queries.append(query)

        songs_added_info = []
        if len(search_queries) > 1:
            await interaction.followup.send(f"✅ Przetwarzam `{len(search_queries)}` utworów...")

        for search_query in search_queries:
            song_info, error = await self.search_song_on_yt(search_query)
            if song_info:
                self.queues[guild_id].append(song_info)
                songs_added_info.append(song_info)

        if not songs_added_info:
            return await interaction.edit_original_response(content="Nie udało się znaleźć żadnych pasujących utworów.")

        if len(songs_added_info) > 1:
            await interaction.edit_original_response(content=f"✅ Dodano `{len(songs_added_info)}` utworów do kolejki.")
        elif not vc.is_playing():
             await interaction.delete_original_response()
        else:
             await interaction.followup.send(f"✅ Dodano **{songs_added_info[0]['title']}** do kolejki.")

        if not vc.is_playing() and self.queues[guild_id]:
            await self.play_next(interaction)

    @app_commands.command(name="volume", description="Ustawia głośność bota (1-200%).")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def volume(self, interaction: Interaction, poziom: app_commands.Range[int, 1, 200]):
        vc = interaction.guild.voice_client
        if not vc or not vc.source:
            return await interaction.response.send_message("Bot niczego nie odtwarza.", ephemeral=True)
        vc.source.volume = poziom / 100.0
        await interaction.response.send_message(f"✅ Ustawiono głośność na **{poziom}%**.", ephemeral=True)

    @app_commands.command(name="skip", description="Pomija aktualnie odtwarzany utwór.")
    async def skip(self, interaction: Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.stop()
            if not interaction.response.is_done():
                await interaction.response.send_message("Pominięto utwór.", ephemeral=True)
        else:
            await interaction.response.send_message("Nic nie jest teraz odtwarzane.", ephemeral=True)

    @app_commands.command(name="stop", description="Zatrzymuje muzykę i czyści kolejkę.")
    async def stop(self, interaction: Interaction):
        vc = interaction.guild.voice_client
        if vc:
            self.queues[interaction.guild.id] = []
            vc.stop()
        if not interaction.response.is_done():
            await interaction.response.send_message("⏹️ Zatrzymałem muzykę.")

    @app_commands.command(name="nowplaying", description="Wyświetla informacje o obecnym utworze.")
    async def nowplaying(self, interaction: Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.source:
            song_info = vc.source.original_song_info
            embed = discord.Embed(title="🎵 Teraz odtwarzane", description=f"**[{song_info.get('title', 'Brak tytułu')}]({song_info.get('url')})**", color=discord.Color.green())
            if thumbnail := song_info.get('thumbnail'): embed.set_thumbnail(url=thumbnail)
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message("Nic nie jest teraz odtwarzane.", ephemeral=True)

    @app_commands.command(name="queue", description="Wyświetla kolejkę utworów.")
    async def queue(self, interaction: Interaction):
        queue = self.get_queue(interaction.guild.id)
        embed = discord.Embed(title="🎶 Kolejka Odtwarzania", color=discord.Color.purple())
        description = ""
        vc = interaction.guild.voice_client
        if vc and vc.source:
            song_info = vc.source.original_song_info
            description += f"**Teraz gram:** [{song_info['title']}]({song_info['url']})\n\n"
        if not queue:
            description += "Kolejka jest pusta."
        else:
            description += "**W kolejce:**\n"
            description += "".join(f"**{i}.** {song['title']}\n" for i, song in enumerate(queue[:15], 1))
            if len(queue) > 15: description += f"\n... i {len(queue) - 15} więcej."
        embed.description = description
        await interaction.response.send_message(embed=embed)

# =================================================================
# SEKCJA 5: URUCHOMIENIE BOTA
# =================================================================
if __name__ == "__main__":
    token = os.getenv("TOKEN")
    if not token:
        print("BŁĄD: Nie znaleziono tokenu w Replit Secrets.")
    else:
       
        try:
            bot.run(token)
        except discord.errors.HTTPException as e:
            if e.status == 429: print("BŁĄD KRYTYCZNY: Zbyt wiele żądań (Rate Limited).")
            else: print(f"Wystąpił błąd HTTP podczas uruchamiania bota: {e}")
        except Exception as e:
            print(f"Wystąpił krytyczny błąd podczas uruchamiania bota: {e}")