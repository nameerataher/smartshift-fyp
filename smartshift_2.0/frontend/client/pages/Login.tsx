import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Sun, Mail, Lock, User, Building2, Eye, EyeOff } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { useMode } from "@/hooks/useMode";

export default function Login() {
  const navigate = useNavigate();
  const { login, register } = useAuth();
  const { setMode } = useMode();
  const [isRegister, setIsRegister] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [userType, setUserType] = useState<"personal" | "commercial">("personal");
  const [organization, setOrganization] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    if (isRegister) {
      const result = await register(email, password, displayName, userType, organization);
      if (result.success) {
        setMode(userType);
        navigate(userType === "commercial" ? "/dashboard" : "/map");
      } else {
        setError(result.error || "Registration failed");
      }
    } else {
      const result = await login(email, password);
      if (result.success) {
        navigate("/dashboard");
      } else {
        setError(result.error || "Login failed");
      }
    }
    setLoading(false);
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-background via-background to-slate-50 dark:to-slate-900 flex items-center justify-center px-4">
      <div className="w-full max-w-md">
        <Link to="/" className="flex items-center justify-center gap-3 mb-8">
          <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-primary to-amber-400 flex items-center justify-center shadow-lg">
            <Sun className="w-7 h-7 text-primary-foreground" />
          </div>
          <span className="text-2xl font-bold text-foreground">SmartShift</span>
        </Link>

        <div className="bg-card border border-border rounded-2xl shadow-xl p-8">
          <h2 className="text-2xl font-bold text-foreground text-center mb-2">
            {isRegister ? "Create Account" : "Welcome Back"}
          </h2>
          <p className="text-sm text-muted-foreground text-center mb-6">
            {isRegister ? "Start optimizing your outdoor work" : "Sign in to your SmartShift account"}
          </p>

          {!isRegister && (
            <div className="mb-6 p-3 rounded-xl bg-muted/50 border border-border">
              <p className="text-xs font-semibold text-muted-foreground mb-2">Demo Accounts</p>
              <div className="space-y-1 text-xs text-muted-foreground">
                <div className="flex justify-between">
                  <span>ahmed@constructco.com</span>
                  <span className="text-primary font-medium">Commercial</span>
                </div>
                <div className="flex justify-between">
                  <span>mike@gmail.com</span>
                  <span className="text-primary font-medium">Personal</span>
                </div>
                <p className="text-[10px] mt-1 opacity-70">Password: password123</p>
              </div>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            {isRegister && (
              <>
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1.5">Full Name</label>
                  <div className="relative">
                    <User className="absolute left-3 top-2.5 w-4 h-4 text-muted-foreground" />
                    <input
                      type="text" required value={displayName}
                      onChange={(e) => setDisplayName(e.target.value)}
                      placeholder="Your name"
                      className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
                    />
                  </div>
                </div>
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1.5">Account Type</label>
                  <div className="grid grid-cols-2 gap-2">
                    <button type="button" onClick={() => setUserType("personal")}
                      className={`p-3 rounded-xl border-2 text-sm font-medium transition-all ${userType === "personal" ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground hover:bg-muted"}`}>
                      Personal
                    </button>
                    <button type="button" onClick={() => setUserType("commercial")}
                      className={`p-3 rounded-xl border-2 text-sm font-medium transition-all ${userType === "commercial" ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground hover:bg-muted"}`}>
                      Commercial
                    </button>
                  </div>
                </div>
                {userType === "commercial" && (
                  <div>
                    <label className="block text-sm font-medium text-foreground mb-1.5">Organization</label>
                    <div className="relative">
                      <Building2 className="absolute left-3 top-2.5 w-4 h-4 text-muted-foreground" />
                      <input
                        type="text" value={organization}
                        onChange={(e) => setOrganization(e.target.value)}
                        placeholder="Company name"
                        className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
                      />
                    </div>
                  </div>
                )}
              </>
            )}

            <div>
              <label className="block text-sm font-medium text-foreground mb-1.5">Email</label>
              <div className="relative">
                <Mail className="absolute left-3 top-2.5 w-4 h-4 text-muted-foreground" />
                <input
                  type="email" required value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-foreground mb-1.5">Password</label>
              <div className="relative">
                <Lock className="absolute left-3 top-2.5 w-4 h-4 text-muted-foreground" />
                <input
                  type={showPassword ? "text" : "password"} required value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Enter password"
                  className="w-full pl-10 pr-10 py-2.5 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
                />
                <button type="button" onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-2.5 text-muted-foreground hover:text-foreground">
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            {error && (
              <div className="p-3 rounded-xl bg-red-50 border border-red-200 text-red-700 text-sm">
                {error}
              </div>
            )}

            <button type="submit" disabled={loading}
              className="w-full py-3 rounded-xl bg-primary text-primary-foreground font-semibold hover:bg-primary/90 transition-colors disabled:opacity-50 shadow-md">
              {loading ? "Please wait..." : isRegister ? "Create Account" : "Sign In"}
            </button>
          </form>

          <div className="mt-6 text-center text-sm text-muted-foreground">
            {isRegister ? "Already have an account?" : "Don't have an account?"}{" "}
            <button onClick={() => { setIsRegister(!isRegister); setError(""); }}
              className="text-primary font-semibold hover:underline">
              {isRegister ? "Sign In" : "Create Account"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
