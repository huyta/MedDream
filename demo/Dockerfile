# ==========================================
# MedDream DICOM Study Hub - Dockerfile
# ==========================================
FROM node:20-alpine

# Set working directory
WORKDIR /app

# Install dependencies
COPY package*.json ./
RUN npm install --omit=dev

# Copy application source code
COPY server.js ./
COPY public ./public

# Set default environment variables
ENV NODE_ENV=production
ENV APP_PORT=3000
ENV ORTHANC_HOST=orthanc
ENV ORTHANC_HTTP_PORT=8042
ENV ORTHANC_USER=orthanc
ENV ORTHANC_PASSWORD=orthanc
ENV MEDDREAM_PORT=8080
ENV MEDDREAM_HOST=localhost

# Expose web application port
EXPOSE 3000

# Healthcheck
HEALTHCHECK --interval=15s --timeout=3s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:3000/api/health || exit 1

# Start the Express server
CMD ["node", "server.js"]
