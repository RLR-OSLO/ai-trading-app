import AuthGate from "./auth-gate";
import TradingDashboard from "./trading-dashboard";

export default function Dashboard() {
  return (
    <AuthGate>
      <TradingDashboard />
    </AuthGate>
  );
}
