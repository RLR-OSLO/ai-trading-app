import { createHmac } from "node:crypto";
import { NextResponse } from "next/server";

export const runtime = "nodejs";

export async function POST(request: Request) {
  try {
    const body = await request.json() as { apiKey?: string; apiSecret?: string };
    const apiKey = String(body.apiKey ?? "").trim();
    const apiSecret = String(body.apiSecret ?? "").trim();
    if (apiKey.length < 16 || apiSecret.length < 16) {
      return NextResponse.json({ ok: false, error: "API key eller secret ser ugyldig ut." }, { status: 400 });
    }

    const timestamp = Date.now();
    const query = `timestamp=${timestamp}&recvWindow=5000`;
    const signature = createHmac("sha256", apiSecret).update(query).digest("hex");
    const response = await fetch(`https://api.binance.com/api/v3/account?${query}&signature=${signature}`, {
      headers: { "X-MBX-APIKEY": apiKey },
      cache: "no-store",
    });
    const payload = await response.json();
    if (!response.ok) {
      const message = typeof payload?.msg === "string" ? payload.msg : "Binance avviste API-nøkkelen.";
      return NextResponse.json({ ok: false, error: message }, { status: 400 });
    }
    if (payload?.canTrade === false) {
      return NextResponse.json({ ok: false, error: "API-nøkkelen har ikke Spot trading aktivert." }, { status: 400 });
    }

    return NextResponse.json({ ok: true });
  } catch {
    return NextResponse.json({ ok: false, error: "Kunne ikke verifisere Binance-kontoen akkurat nå." }, { status: 500 });
  }
}
