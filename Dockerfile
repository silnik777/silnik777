# Obraz pod przyszłe wdrożenie webowe (Azure App Service / Container Apps).
# Lokalne uruchomienie: docker build -t gas-rd-tool . && docker run -p 8501:8501 gas-rd-tool
FROM python:3.11-slim

WORKDIR /srv/app

# Najpierw zależności (lepsze cache'owanie warstw)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY core/ core/
COPY app/ app/
COPY data/ data/

ENV APP_ENV=web \
    PYTHONUNBUFFERED=1

EXPOSE 8501

HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"

CMD ["streamlit", "run", "app/main.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
