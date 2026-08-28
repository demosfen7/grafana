FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY weather_app.py http_client.py ./

CMD ["python", "weather_app.py"]
