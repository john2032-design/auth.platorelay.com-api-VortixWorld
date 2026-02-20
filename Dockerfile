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

# Force-set include path in binding.gyp by overwriting the include_dirs section
RUN sed -i '/"include_dirs": \[/,/]/c\    "include_dirs": [\n        "<(opencv_include_dir)",\n        "/usr/include/opencv4",\n        "/usr/include/opencv4/opencv2",\n        "<(node_root_dir)/include/node",\n        "<(node_root_dir)/deps/v8/include"\n    ]' node_modules/@u4/opencv4nodejs/binding.gyp

RUN cd node_modules/@u4/opencv4nodejs && node-gyp rebuild

COPY . .

EXPOSE 3000

CMD ["npm", "start"]