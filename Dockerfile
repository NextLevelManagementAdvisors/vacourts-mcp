FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py ./
EXPOSE 3032
CMD ["python", "-m", "server", "--transport", "http"]
