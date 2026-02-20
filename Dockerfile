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

RUN cat > /tmp/binding.gyp << 'EOF'
{
  "targets": [
    {
      "target_name": "opencv4nodejs",
      "sources": ["cc/opencv4nodejs.cc"],
      "include_dirs": [
        "<!(node -e \"require('nan')\")",
        "/usr/include/opencv4",
        "/usr/include/opencv4/opencv2",
        "<(node_root_dir)/include/node",
        "<(node_root_dir)/deps/v8/include"
      ],
      "libraries": [
        "-lopencv_core",
        "-lopencv_imgproc",
        "-lopencv_highgui",
        "-lopencv_imgcodecs",
        "-lopencv_videoio",
        "-lopencv_ml",
        "-lopencv_video",
        "-lopencv_objdetect",
        "-lopencv_calib3d",
        "-lopencv_features2d",
        "-lopencv_dnn",
        "-lopencv_flann",
        "-lopencv_photo",
        "-lopencv_shape",
        "-lopencv_stitching",
        "-lopencv_superres",
        "-lopencv_videostab",
        "-lopencv_viz"
      ],
      "cflags": ["-std=c++11"],
      "conditions": [["OS=='linux'", {"libraries": ["-L/usr/lib/x86_64-linux-gnu"] }]]
    }
  ]
}
EOF

RUN cp /tmp/binding.gyp node_modules/@u4/opencv4nodejs/binding.gyp

RUN cd node_modules/@u4/opencv4nodejs && node-gyp rebuild

COPY . .

EXPOSE 3000

CMD ["npm", "start"]