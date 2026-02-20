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

RUN npm install -g node-gyp

RUN npm install

RUN sed -i '/"include_dirs": \[/a \        "/usr/include/opencv4",' node_modules/@u4/opencv4nodejs/binding.gyp

RUN cd node_modules/@u4/opencv4nodejs && node-gyp rebuild

COPY . .

EXPOSE 3000

CMD ["npm", "start"]