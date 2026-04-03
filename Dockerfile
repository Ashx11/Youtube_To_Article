# Stage 1: Build frontend
FROM node:18-alpine AS frontend-build
WORKDIR /build-frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Backend + serve frontend
FROM python:3.11-slim
WORKDIR /app

# Install Node for serving frontend
RUN apt-get update && apt-get install -y nodejs npm && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend
COPY backend/ ./backend/

# Copy frontend build
COPY --from=frontend-build /build-frontend/dist ./frontend/dist

# Install serve for frontend
RUN npm install -g serve

EXPOSE 8000 5173

# Run both services
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 &\nserve -s frontend/dist -l 5173"]