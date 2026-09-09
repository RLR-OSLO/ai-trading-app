export default function HowItWorks() {
  const points = [
    {
      title: "Scanner bare markeder vi faktisk kan komme oss ut av",
      text: "Boten filtrerer bort tynne markeder og ser etter høy omsetning, mange handler og lav spread før et marked får være med i utvalget.",
    },
    {
      title: "Rangerer de sterkeste mulighetene fortløpende",
      text: "Den sammenligner trend, momentum, volum og flere tidsrammer for å finne hvilke kryptovalutaer som har best oppsett akkurat nå.",
    },
    {
      title: "Bruker ulike strategier etter markedssituasjonen",
      text: "Vanlige trendhandler håndteres som swing, raske kortsiktige oppsett som scalp, og ekstra sterke bevegelser kan gå over i Bull Run-modus.",
    },
    {
      title: "Lar sterke vinnere løpe",
      text: "Når en handel går riktig vei kan boten aktivere trailing i stedet for å selge på et fast gevinstmål. Dermed kan den følge en sterk trend videre opp og sikre gevinst når momentet snur.",
    },
    {
      title: "Tilpasser stop og størrelse innenfor sikkerhetsrammene",
      text: "Stop-loss, trailing og posisjonsstørrelse kan tilpasses volatilitet og styrken i oppsettet, men boten må fortsatt holde seg innenfor definerte risiko- og tapsgrenser.",
    },
    {
      title: "Er bygget som daytrader – ikke som langsiktig investor",
      text: "Målet er å finne gode bevegelser tidlig, ta kontrollerte posisjoner og komme ut igjen når oppsettet svekkes. Scalp-handler har korte tidsgrenser, og Bull Run-handler får mer spillerom når markedet er sterkt.",
    },
    {
      title: "Binance er fasit for pengene",
      text: "Saldo, reelle beholdninger og markedsverdi hentes fra Binance. Supabase brukes til historikk, innstillinger og rapportering – ikke som fasit for hva som faktisk eies.",
    },
    {
      title: "Har flere lag med risikokontroll",
      text: "Boten bruker hard stop, trailing stop, maks dagstap, begrensning på antall handler, cooldown og maks antall samtidige posisjoner. Spot-only betyr også ingen giring, futures eller margin.",
    },
  ];

  return (
    <section className="panel" style={{ marginTop: 18 }}>
      <div className="panel-head">
        <div>
          <p className="eyebrow">SLIK FUNGERER MODELLEN</p>
          <h3>Hva tradingroboten gjør i praksis</h3>
        </div>
        <span className="muted">Adaptiv daytrading · Spot only</span>
      </div>
      <p className="muted" style={{ maxWidth: 980, marginBottom: 18 }}>
        Robotens jobb er ikke å gjette én perfekt pris. Den prøver i stedet å finne de mest likvide markedene,
        oppdage hvor styrken er størst, velge riktig handelsmodus og styre risikoen mens posisjonen utvikler seg.
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 12 }}>
        {points.map((point) => (
          <article key={point.title} style={{ border: "1px solid rgba(148,163,184,.18)", borderRadius: 14, padding: 16, background: "rgba(15,23,42,.35)" }}>
            <strong style={{ display: "block", marginBottom: 7 }}>{point.title}</strong>
            <small style={{ display: "block", lineHeight: 1.55 }}>{point.text}</small>
          </article>
        ))}
      </div>
      <p className="muted" style={{ marginTop: 16, marginBottom: 0 }}>
        Viktig: modellen er laget for å forbedre sannsynlighet og risikostyring – den kan ikke garantere gevinst i hver handel eller over enhver periode.
      </p>
    </section>
  );
}
