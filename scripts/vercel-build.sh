#!/bin/sh
set -e
# Apex path layout on aibusinessagent.xyz:
#   /           marketing (website/)
#   /agents/*   product SPA (frontend/ → public/agents/)
#   /bay/*      AgentBay SPA (bay-dist/ → public/bay/)
#   /api/*      FastAPI (api/index.py)
cd frontend
VITE_BASE=/agents/ npm run build
cd ..
rm -rf public
mkdir -p public/agents
cp -R frontend/dist/. public/agents/
# Landing site last so marketing owns / (not SPA)
cp -R website/. public/
rm -f public/vercel.json public/package.json public/README.md
if [ -d bay-dist ]; then
  mkdir -p public/bay
  cp -R bay-dist/. public/bay/
  # Ensure bay index exists for /bay rewrite
  if [ ! -f public/bay/index.html ]; then
    echo "warning: bay-dist missing index.html" >&2
  fi
fi
# Sanity: landing must be at public/index.html for apex /
if [ ! -f public/index.html ]; then
  echo "error: marketing index.html missing after build" >&2
  exit 1
fi

