# Playwright Web Crawler Agent — PRD

## Problem Statement
Build a complete Playwright Web Crawler Agent application where users enter a URL, optionally provide login credentials, click "Start Crawl", and a real visible Chrome browser opens. The agent visits every page automatically, detects/bypasses login pages intelligently, shows all crawled pages with status codes and screenshots live in the UI via WebSocket, and generates a final downloadable JSON report.

## Architecture

### Backend (FastAPI on port 8001)
- `server.py` — FastAPI app with crawler routes, WebSocket endpoint, in-memory session management
- `crawler.py` — Playwright BFS crawler with Xvfb (headed mode), screenshot capture, AI analysis
- `ai_agent.py` — Claude AI (claude-4-sonnet-20250514) page analysis via emergentintegrations
- `login_handler.py` — Login form detection, auto-fill, CAPTCHA detection
- `utils.py` — URL normalization, domain filtering, skip-extension helpers

### Frontend (React on port 3000)
- `App.js` — Single-page UI with WebSocket live updates, log panel, pages grid, modal
- `App.css` — Dark GitHub-inspired terminal theme (#0d1117 background)

## Core Requirements (Static)
1. Headed browser via Xvfb virtual display
2. BFS crawl with configurable max_pages (1-200) and max_depth (1-5)
3. Real-time WebSocket events streamed to frontend
4. Screenshots captured as base64 PNG per page
5. Claude AI analyzes each page for type, elements, risk level
6. Login form detection and auto-fill bypass
7. In-memory session storage with JSON report export
8. Dark terminal UI (#0d1117, #e6edf3, monospace font)

## API Endpoints
- `POST /api/crawl/start` → `{session_id}`
- `GET /api/crawl/{id}/status` → session status + stats
- `GET /api/crawl/{id}/report` → full JSON report with pages
- `POST /api/crawl/{id}/stop` → stop crawl
- `WS /api/ws/{session_id}` → live events stream

## WebSocket Events
- `crawl_started`, `page_visited`, `page_error`
- `login_detected`, `login_success`, `login_failed`
- `crawl_complete`, `crawl_error`, `crawl_stopped`

## What's Been Implemented (April 2026)
- [x] Full FastAPI backend with crawler routes and WebSocket
- [x] Playwright BFS crawler with Xvfb headed mode
- [x] Claude AI integration via Emergent Universal Key
- [x] Login form detection and auto-bypass
- [x] URL deduplication, same-domain filtering
- [x] Screenshot capture as base64 PNG
- [x] React frontend with dark terminal theme
- [x] Live log panel with auto-scroll
- [x] Pages grid with screenshot thumbnails
- [x] Page detail modal
- [x] Stats bar (pages, errors, auth-required, elapsed timer)
- [x] Download Report button
- [x] Stop crawl button
- [x] 100% test pass rate (backend + frontend)

## Environment
- EMERGENT_LLM_KEY in /app/backend/.env
- PLAYWRIGHT_BROWSERS_PATH=/pw-browsers (set in crawler.py)
- Xvfb display :99 (auto-started by crawler)

## Prioritized Backlog

### P0 (MVP complete)
- [x] All core crawl features

### P1 (Next phase)
- [ ] Persist crawl sessions to MongoDB (survives restarts)
- [ ] robots.txt respect
- [ ] Export report as CSV or HTML
- [ ] Retry failed pages
- [ ] Screenshot gallery view (full-page scrolling)

### P2 (Nice to have)
- [ ] Multi-tab concurrent crawling
- [ ] Proxy support
- [ ] Cookie/session file import
- [ ] Sitemap.xml parsing for seed URLs
- [ ] Email report delivery
