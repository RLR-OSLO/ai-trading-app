import { futuresStatus, type futuresWallet } from "../lib/trading-wallet";

export default function FuturesBalance({wallet, quote}: {wallet: ReturnType<typeof futuresWallet>; quote: string}) {
  const amount = (value: number | null) => value === null ? "Ukjent" : value.toLocaleString("nb-NO", {maximumFractionDigits: 2});
  return <div>
    <span className="label">FUTURES TOTALT</span>
    <strong>{amount(wallet.value)} {quote}</strong>
    <small>Disponibel margin: {amount(wallet.available)} {quote}</small>
    <small>Margin til posisjoner: {amount(wallet.positionMargin)} · Til åpne ordre: {amount(wallet.orderMargin)} {quote}</small>
    {wallet.assets.length > 0 && <small>Saldo per valuta: {wallet.assets.map(row => `${amount(row.balance)} ${row.asset}`).join(" · ")}</small>}
    {wallet.mode === "multi" && <small>Felles margin på tvers av valutaer · omregnet til {quote}</small>}
    <small role="status">{futuresStatus(wallet.status)}</small>
  </div>;
}
