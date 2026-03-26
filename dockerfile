# Gebruik een officiële, lichte Python image als basis
FROM python:3.11-slim

# Zet de werkmap in de container
WORKDIR /app

# Kopieer eerst het requirements bestand naar de werkmap
COPY requirements.txt .

# Installeer de benodigde Python pakketten
RUN pip install --no-cache-dir -r requirements.txt

# Kopieer de rest van je project (app.py en templates map) naar de container
COPY . .

# Geef aan dat de container poort 5000 (TCP) gebruikt
EXPOSE 5000

# Start de Flask applicatie wanneer de container start
CMD ["python", "app.py"]