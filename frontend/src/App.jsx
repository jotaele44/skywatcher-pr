import { Toaster } from "@/components/ui/toaster"
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClientInstance } from '@/lib/query-client'
import { BrowserRouter as Router, Route, Routes } from 'react-router-dom';
import PageNotFound from './lib/PageNotFound';
import ErrorBoundary from '@/components/ErrorBoundary';
import { AuthProvider } from '@/lib/AuthContext';
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
import Login from '@/pages/Login';
import Register from '@/pages/Register';
import ForgotPassword from '@/pages/ForgotPassword';
import ResetPassword from '@/pages/ResetPassword';

const AuthenticatedApp = () => {
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
          </Route>
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/forgot-password" element={<ForgotPassword />} />
          <Route path="/reset-password" element={<ResetPassword />} />
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
