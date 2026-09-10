import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const revalidate = 60;

type Kline = [number, string, string, string, string, string, number, string, number, string, string, string];

const SYMBOL_RE = /^[A-Z0-9]{5,20}$/;
const BASE_URLS = ["https://data-api.binance.vision", "https://api.binance.com"];

async function loadKlines(symbol: string): Promise<Kline[]> {
  for (const base of BASE_URLS) {
    try {
      const url = `${base}/api/v3/klines?symbol=${encodeURIComponent(symbol)}&interval=15m&limit=49`;
      const response = await fetch(url, {
        cache: "no-store",
        headers: { "User-Agent": "ai-trading-app-market-history/1.0" },
      });
      if (!response.ok) continue;
      const rows = await response.json();
      if (Array.isArray(rows) && rows.length > 1) return rows as Kline[];
    } catch {
      // Try next public Binance market-data endpoint.
    }
  }
  return [];
}

export async function GET(request: NextRequest) {
  const raw = request.nextUrl.searchParams.get("symbols") ?? "";
  const symbols = Array.from(new Set(raw.split(",").map((s) => s.trim().toUpperCase()).filter((s) => SYMBOL_RE.test(s)))).slice(0, 30);
  if (!symbols.length) return NextResponse.json({ series: {} });

  const entries = await Promise.all(symbols.map(async (symbol) => {
    const rows = await loadKlines(symbol);
    const points = rows
      .map((row) => ({ t: Number(row[0]), c: Number(row[4]) }))
      .filter((p) => Number.isFinite(p.t) && Number.isFinite(p.c));
    return [symbol, points] as const;
  }));

  return NextResponse.json({ series: Object.fromEntries(entries) }, {
    headers: { "Cache-Control": "public, s-maxage=60, stale-while-revalidate=120" },
  });
}
