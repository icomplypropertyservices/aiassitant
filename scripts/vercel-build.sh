#!/bin/sh
set -e
cd frontend
VITE_BASE=/agents/ npm run build
cd ..
rm -rf public
mkdir -p public/agents
cp -R frontend/dist/. public/agents/
cp -R website/. public/
rm -f public/vercel.json public/package.json public/README.md
if [ -d bay-dist ]; then
  mkdir -p public/bay
  cp -R bay-dist/. public/bay/
fi
