import { Toaster } from "@/components/ui/toaster"
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClientInstance } from '@/lib/query-client'
import { BrowserRouter as Router, Route, Routes, Navigate, useLocation } from 'react-router-dom';
import PageNotFound from './lib/PageNotFound';
import ErrorBoundary from '@/components/ErrorBoundary';
import { AuthProvider, useAuth } from '@/lib/AuthContext';
import { SkywatcherDataProvider } from '@/lib/SkywatcherData';
import { DrawerHubProvider } from '@/components/skywatcher/drawers/DrawerHub';
import Layout from '@/components/skywatcher/Layout';
import Dashboard from '@/pages/Dashboard';
import Console from '@/pages/Console';
import Observations from '@/pages/Observations';
import Aircraft from '@/pages/Aircraft';
import FR24Intake from '@/pages/FR24Intake';
import RoutesPage from '@/pages/Routes';
import Infrastructure from '@/pages/Infrastructure';
import Airports from '@/pages/Airports';
import ManualReview from '@/pages/ManualReview';
import ExportCenter from '@/pages/ExportCenter';
import Readiness from '@/pages/Readiness';
import Calibration from '@/pages/Calibration';
import AnalysisLenses from '@/pages/AnalysisLenses';
import SpatialTruth from '@/pages/SpatialTruth';
import Login from '@/pages/Login';
import Register from '@/pages/Register';
import ForgotPassword from '@/pages/ForgotPassword';
import ResetPassword from '@/pages/ResetPassword';
import LoadingState from '@/components/skywatcher/LoadingState';
import { appParams } from '@/lib/app-params';

const AuthenticatedApp = () => {
  const { appPublicSettings, isLoadingPublicSettings, isLoadingAuth, isAuthenticated, authError, checkAppState } = useAuth();
  const location = useLocation();

  // Wait for public settings before routing. appPublicSettings is null until
  // AuthContext.checkAppState() resolves, so routing on it early would treat a
  // backend that reports requires_auth=true as diagnostic mode for one render —
  // long enough to redirect a direct visit to /login away to /, after which the
  // login page is unreachable because the URL has already changed.
  if (isLoadingPublicSettings || isLoadingAuth) {
    return <LoadingState />;
  }

  if (!appPublicSettings || authError?.type === 'unknown') {
    return <main className="min-h-screen flex items-center justify-center p-6">
      <div role="alert" className="max-w-md space-y-4">
        <h1 className="text-xl font-semibold">Unable to verify application access</h1>
        <p>The server settings or account check could not be completed. Your current page will be preserved while you retry.</p>
        <button type="button" className="rounded border px-4 py-2" onClick={checkAppState}>Retry connection</button>
      </div>
    </main>;
  }

  // Same signal AuthContext uses to decide whether authentication is required.
  const authRequired = Boolean(
    appPublicSettings?.public_settings?.requires_auth || appParams.requireAuth
  );

  // Authentication pages must not mount the data provider or issue protected
  // collection requests before sign-in. Authorization still belongs to the API.
  if (authRequired) {
    if (['/login', '/register', '/forgot-password', '/reset-password'].includes(location.pathname)) {
      return <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />
      </Routes>;
    }
    if (!isAuthenticated) {
      return <Navigate to={`/login?redirect=${encodeURIComponent(location.pathname + location.search + location.hash)}`} replace />;
    }
  }

  return (
    <SkywatcherDataProvider>
      <DrawerHubProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/console" element={<Console />} />
            <Route path="/observations" element={<Observations />} />
            <Route path="/aircraft" element={<Aircraft />} />
            <Route path="/fr24" element={<FR24Intake />} />
            <Route path="/routes" element={<RoutesPage />} />
            <Route path="/infrastructure" element={<Infrastructure />} />
            <Route path="/airports" element={<Airports />} />
            <Route path="/review" element={<ManualReview />} />
            <Route path="/export" element={<ExportCenter />} />
            <Route path="/readiness" element={<Readiness />} />
            <Route path="/calibration" element={<Calibration />} />
            <Route path="/analysis" element={<AnalysisLenses />} />
            <Route path="/spatial-truth" element={<SpatialTruth />} />
          </Route>
          {/* Diagnostic mode has no account provider; these links return home. */}
          <Route path="/login" element={<Navigate to="/" replace />} />
          <Route path="/register" element={<Navigate to="/" replace />} />
          <Route path="/forgot-password" element={<Navigate to="/" replace />} />
          <Route path="/reset-password" element={<Navigate to="/" replace />} />
          <Route path="*" element={<PageNotFound />} />
        </Routes>
      </DrawerHubProvider>
    </SkywatcherDataProvider>
  );
};

function App() {
  return (
    <ErrorBoundary>
      <AuthProvider>
        <QueryClientProvider client={queryClientInstance}>
          <Router>
            <AuthenticatedApp />
          </Router>
          <Toaster />
        </QueryClientProvider>
      </AuthProvider>
    </ErrorBoundary>
  )
}

export default App
