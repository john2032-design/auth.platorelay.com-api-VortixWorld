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

ENV OPENCV4NODEJS_DISABLE_AUTOBUILD=1
ENV OPENCV_INCLUDE_DIR=/usr/include/opencv4
ENV OPENCV_LIB_DIR=/usr/lib/x86_64-linux-gnu
ENV OPENCV_BIN_DIR=/usr/bin

COPY package*.json ./

RUN npm install

RUN cd node_modules/@u4/opencv4nodejs && node-gyp rebuild

COPY . .

EXPOSE 3000

CMD ["npm", "start"]