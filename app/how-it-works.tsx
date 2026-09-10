export default function HowItWorks() {
  const points = [
    {
      title: "Scanner bare markeder med god nok likviditet",
      text: "Boten filtrerer bort tynne markeder og prioriterer høy omsetning, mange handler og lav spread. Utvalget rangeres på nytt fortløpende.",
    },
    {
      title: "Analyserer både oppgang og nedgang",
      text: "Trend, momentum, volum, volatilitet og flere tidsrammer brukes både til vanlige kjøpssignaler og egne bearish-signaler for shorting.",
    },
    {
      title: "Velger strategi etter markedet",
      text: "Spot brukes for long-posisjoner. Margin-short kan brukes på Høy og Ekstrem risiko. Futures kan brukes på Ekstrem risiko når det er aktivert av brukeren.",
    },
    {
      title: "Tilpasser størrelsen dynamisk",
      text: "Boten trenger ikke bruke samme beløp på hver handel. Signalstyrke og strategi bestemmer faktisk størrelse, men den kan aldri overskride brukerens maks per posisjon eller maks botkapital.",
    },
    {
      title: "Lar sterke vinnere løpe",
      text: "Spot-handler kan bruke trailing i stedet for et statisk gevinstpunkt. Målet er å beskytte gevinst når markedet snur, uten å kutte sterke bevegelser for tidlig.",
    },
    {
      title: "Shorting har egen beskyttelse",
      text: "Margin-short åpnes ved å låne og selge, og lukkes ved å kjøpe tilbake og tilbakebetale. Futures-short åpnes separat og har egne stop-loss- og take-profit-ordrer.",
    },
    {
      title: "Futures bruker isolert margin og begrenset gearing",
      text: "Når Futures er slått på brukes isolated margin. Gearing er begrenset til 1x–3x og styres av brukeren. Futures er kun tilgjengelig på Ekstrem risiko.",
    },
    {
      title: "Én felles tapsgrense beskytter hele boten",
      text: "Realisert resultat fra spot og derivater inngår i samme daglige risikovurdering. Når tapsgrensen er nådd blokkeres nye posisjoner.",
    },
    {
      title: "Binance er fasit for penger og posisjoner",
      text: "Reelle saldi og markedsverdier hentes fra Binance. Supabase brukes til innstillinger, historikk, hendelser og kontrollinformasjon.",
    },
    {
      title: "Hver bruker er teknisk isolert",
      text: "Hver innlogget bruker har egne innstillinger, handler, hendelser, API-tilkobling og egne state-filer på serveren. Kontoer skal aldri dele tradingstate eller data.",
    },
    {
      title: "Samme funksjoner for alle godkjente brukere",
      text: "Alle kjører samme kodebase og samme funksjoner, men med egne Binance-nøkler, egne grenser og egne posisjoner. Dette gjør løsningen egnet for noen få separate brukere uten sammenblanding.",
    },
    {
      title: "Sikkerhetslåser gjelder før avkastning",
      text: "Uttak via API er deaktivert, IP-tilgangen er begrenset, nye handler kan pauses, og stop-/exit-logikk fortsetter å håndtere åpne posisjoner når nye entries er stoppet.",
    },
  ];

  return (
    <section className="panel" style={{ marginTop: 18 }}>
      <div className="panel-head">
        <div>
          <p className="eyebrow">SLIK FUNGERER BOTEN</p>
          <h3>Fra markedsscan til handel og risikokontroll</h3>
        </div>
        <span className="muted">Spot · Margin short · Futures · Dynamisk sizing</span>
      </div>
      <p className="muted" style={{ maxWidth: 1020, marginBottom: 18 }}>
        Boten forsøker ikke å forutsi én perfekt pris. Den scanner likvide markeder, vurderer retning og signalstyrke,
        velger riktig handelsmodus og styrer størrelse, stop og exits innenfor grensene brukeren har satt.
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
        Viktig: modellen er laget for å forbedre beslutningskvalitet og risikostyring. Den kan ikke garantere gevinst, og Margin/Futures kan gi raskere tap enn vanlig spot dersom markedet går feil vei.
      </p>
    </section>
  );
}
