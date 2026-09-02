FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY MWLSCP/ ./MWLSCP/

EXPOSE 11112

VOLUME ["/app/MWLSCP/worklists"]

ENTRYPOINT ["python", "-m", "MWLSCP", "run", "--host", "0.0.0.0", "--port", "11112", "--aet", "MWL_SCP"]
