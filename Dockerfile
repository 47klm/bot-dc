# Używamy oficjalnego obrazu Pythona
FROM python:3.11-slim

# Ustawiamy folder roboczy wewnątrz kontenera
WORKDIR /app

# Instalujemy ffmpeg i inne potrzebne pakiety systemowe
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg

# Kopiujemy plik z wymaganiami i instalujemy biblioteki Pythona
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopiujemy resztę plików bota
COPY . .

# Komenda, która uruchomi bota
CMD ["python", "main.py"]