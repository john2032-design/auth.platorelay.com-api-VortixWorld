FROM node:18-bullseye

RUN apt-get update && apt-get install -y \
    cmake \
    build-essential \
    pkg-config \
    libopencv-dev \
    git \
    python3 \
    make \
    g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package*.json ./

RUN npm install

RUN node -e "const {OpenCVBuilder} = require('@u4/opencv-build'); (async () => { const builder = new OpenCVBuilder(); try { await builder.build(); console.log('OpenCV built successfully'); } catch (e) { console.error('Build failed:', e); process.exit(1); } })();"

COPY . .

EXPOSE 3000

CMD ["npm", "start"]