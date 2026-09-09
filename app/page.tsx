import AdminUsers from "./admin-users";
import AuthGate from "./auth-gate";
import TradingDashboard from "./trading-dashboard";

export default function Dashboard() {
  return (
    <AuthGate>
      <AdminUsers />
      <TradingDashboard />
    </AuthGate>
  );
}
