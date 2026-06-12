FROM python:3.12-slim

WORKDIR /app/mcp-server

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY local-mcp.py devserver-mcp.py ./

# WORKSPACE_ROOT is the project checkout this server reads/writes/runs
# commands in -- mount it as a volume and point this at its container path.
ENV WORKSPACE_ROOT=/workspace

EXPOSE 3100

CMD ["python", "local-mcp.py"]
