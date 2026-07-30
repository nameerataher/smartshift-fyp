import { Link } from "react-router-dom";
import { Sun, Cloud, Navigation, Clock, Map, Target, CloudSun, Cpu, Zap, Mail, Phone, MapPin, Check, CalendarClock, Route } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";
import { ThemeSelect } from "@/components/ThemeSelect";
import { useMode } from "@/hooks/useMode";
import { Logo } from "@/components/Logo";

export default function Index() {
  const { user } = useAuth();
  const { mode, setMode } = useMode();

  const handlePersonalClick = () => {
    setMode("personal");
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-background via-background to-slate-50 dark:from-background dark:via-background dark:to-slate-900">
      {/* Navigation */}
      <nav className="sticky top-0 z-50 backdrop-blur-md bg-background/80 dark:bg-background/80 border-b border-border">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Logo className="w-10 h-10" />
              <span className="font-garet text-xl font-bold text-foreground">ShadeMe</span>
            </div>
            <div className="hidden md:flex items-center gap-4">
              <a href="#" className="text-sm font-medium text-muted-foreground hover:text-foreground transition">Overview</a>
              <a href="#about" className="text-sm font-medium text-muted-foreground hover:text-foreground transition">About</a>
              <a href="#product" className="text-sm font-medium text-muted-foreground hover:text-foreground transition">Product</a>
              <a href="#solutions" className="text-sm font-medium text-muted-foreground hover:text-foreground transition">Solutions</a>
              <a href="#pricing" className="text-sm font-medium text-muted-foreground hover:text-foreground transition">Pricing</a>
              <a href="#contact" className="text-sm font-medium text-muted-foreground hover:text-foreground transition">Contact</a>
              <ThemeSelect variant="compact" />
              {user ? (
                <Link to="/dashboard">
                  <Button size="sm" className="bg-primary hover:bg-primary/90 text-primary-foreground">
                    Dashboard
                  </Button>
                </Link>
              ) : (
                <>
                  <Link to="/login">
                    <Button size="sm" variant="outline">Sign In</Button>
                  </Link>
                  <Link to="/register">
                    <Button size="sm" className="bg-primary hover:bg-primary/90 text-primary-foreground">Get Started</Button>
                  </Link>
                </>
              )}
            </div>
            <div className="md:hidden flex items-center gap-2">
              <ThemeSelect variant="compact" />
              {user ? (
                <Link to="/dashboard">
                  <Button size="sm" className="bg-primary hover:bg-primary/90 text-primary-foreground">Dashboard</Button>
                </Link>
              ) : (
                <>
                  <Link to="/login">
                    <Button size="sm" variant="outline">Sign In</Button>
                  </Link>
                  <Link to="/register">
                    <Button size="sm" className="bg-primary hover:bg-primary/90 text-primary-foreground">Get Started</Button>
                  </Link>
                </>
              )}
            </div>
          </div>
        </div>
      </nav>

      {/* Hero Section */}
      <section className="relative overflow-hidden pt-12 pb-20 sm:pt-16 sm:pb-24">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 items-center">
            <div className="space-y-8">
              <div className="space-y-4">
                <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-primary/10 text-primary border border-primary/20">
                  <span className="text-sm font-semibold">Real-Time Shade Intelligence</span>
                </div>
                <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold text-foreground tracking-tight">
                  Optimize Your Outdoor Work
                </h1>
                <p className="text-lg sm:text-xl text-muted-foreground max-w-xl">
                  ShadeMe predicts shadow patterns, schedules tasks efficiently, and routes you through the safest, coolest paths.
                </p>
              </div>

              <div className="flex flex-col sm:flex-row gap-4">
                <Link to="/map" onClick={() => setMode("commercial")}>
                  <Button size="lg" className="w-full sm:w-auto bg-primary hover:bg-primary/90 text-primary-foreground gap-2">
                    <CalendarClock className="w-5 h-5" />
                    Work Planning
                  </Button>
                </Link>
                <Link to="/map" onClick={handlePersonalClick}>
                  <Button size="lg" className="w-full sm:w-auto gap-2 bg-secondary hover:bg-secondary/90 text-secondary-foreground border-2 border-secondary">
                    <Route className="w-5 h-5" />
                    Route Navigation
                  </Button>
                </Link>
              </div>
            </div>

            <div className="relative h-96 sm:h-full flex items-center justify-center">
              <div className="absolute inset-0 bg-gradient-to-r from-primary/20 to-secondary/20 rounded-3xl blur-3xl"></div>
              <div className="relative bg-gradient-to-br from-primary/5 to-secondary/5 backdrop-blur rounded-3xl p-12 border border-border shadow-2xl">
                <div className="space-y-4">
                  <div className="flex items-center gap-4 p-4 rounded-xl bg-background/50 border border-border">
                    <Sun className="w-8 h-8 text-primary" />
                    <div className="flex-1">
                      <p className="text-sm font-semibold text-foreground">Sun Position</p>
                      <p className="text-xs text-muted-foreground">45 NE, UV Index: 8</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-4 p-4 rounded-xl bg-background/50 border border-border">
                    <Cloud className="w-8 h-8 text-secondary" />
                    <div className="flex-1">
                      <p className="text-sm font-semibold text-foreground">Shadow Coverage</p>
                      <p className="text-xs text-muted-foreground">62% in next 2 hours</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-4 p-4 rounded-xl bg-background/50 border border-border">
                    <Navigation className="w-8 h-8 text-accent" />
                    <div className="flex-1">
                      <p className="text-sm font-semibold text-foreground">Optimal Route</p>
                      <p className="text-xs text-muted-foreground">2.3 km - 15 min - 80% shaded</p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* About Section */}
      <section id="about" className="py-12 sm:py-24 border-t border-border">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center space-y-4 mb-12">
            <h2 className="text-3xl sm:text-4xl font-bold text-foreground">About Us</h2>
            <p className="text-lg text-muted-foreground max-w-2xl mx-auto">
              ShadeMe is a real-time shade tracking and scheduling platform designed to help people
              navigate cities while minimizing exposure to direct sunlight.
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
            <div className="p-6 rounded-2xl bg-card border border-border hover:border-primary/30 transition">
              <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center mb-4">
                <Target className="w-6 h-6 text-primary" />
              </div>
              <h3 className="text-lg font-semibold text-foreground mb-2">Our Mission</h3>
              <p className="text-sm text-muted-foreground">
                Make urban environments more comfortable and accessible by helping companies and individuals avoid excessive sunlight.
              </p>
            </div>
            <div className="p-6 rounded-2xl bg-card border border-border hover:border-primary/30 transition">
              <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center mb-4">
                <CloudSun className="w-6 h-6 text-primary" />
              </div>
              <h3 className="text-lg font-semibold text-foreground mb-2">The Problem We Address</h3>
              <p className="text-sm text-muted-foreground">
                Traditional systems ignore environmental factors such as sun exposure while scheduling tasks and suggesting routes.
              </p>
            </div>
            <div className="p-6 rounded-2xl bg-card border border-border hover:border-primary/30 transition">
              <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center mb-4">
                <Cpu className="w-6 h-6 text-primary" />
              </div>
              <h3 className="text-lg font-semibold text-foreground mb-2">Technology</h3>
              <p className="text-sm text-muted-foreground">
                Integrates solar position algorithms, 3D city modeling, and real-time scheduling with ML-powered recommendations.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Product Section */}
      <section id="product" className="py-12 sm:py-24 border-t border-border">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center space-y-4 mb-12">
            <h2 className="text-3xl sm:text-4xl font-bold text-foreground">Powerful Features</h2>
            <p className="text-lg text-muted-foreground max-w-2xl mx-auto">Advanced technology to keep you safe and productive.</p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
            {[
              { icon: Map, title: "3D Urban Mapping", desc: "Real-time 3D urban models with Mapbox integration for accurate shadow prediction", color: "primary" },
              { icon: Sun, title: "Sun Movement Tracking", desc: "Advanced calculations predict shadow patterns and sun exposure throughout the day", color: "secondary" },
              { icon: Clock, title: "Smart Scheduling", desc: "Optimize task timing based on minimum sun exposure and maximum shade coverage", color: "accent" },
              { icon: Navigation, title: "Heat-Optimized Routing", desc: "Routes that minimize sun exposure with alternate path suggestions", color: "primary" },
              { icon: Zap, title: "Real-Time Alerts", desc: "Instant notifications when heat levels reach dangerous thresholds", color: "secondary" },
              { icon: Cloud, title: "Weather Integration", desc: "Real-time and forecasted heat data for accurate risk assessment", color: "accent" },
            ].map(({ icon: Icon, title, desc, color }) => (
              <div key={title} className={`p-6 rounded-2xl bg-card border border-border hover:border-${color}/30 transition`}>
                <div className={`w-12 h-12 rounded-lg bg-${color}/10 flex items-center justify-center mb-4`}>
                  <Icon className={`w-6 h-6 text-${color}`} />
                </div>
                <h3 className="text-lg font-semibold text-foreground mb-2">{title}</h3>
                <p className="text-sm text-muted-foreground">{desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Solutions Section */}
      <section id="solutions" className="py-12 sm:py-24 border-t border-border bg-card/30">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center space-y-4 mb-12">
            <h2 className="text-3xl sm:text-4xl font-bold text-foreground">Built for Every Need</h2>
            <p className="text-lg text-muted-foreground max-w-2xl mx-auto">
              Whether you're managing a commercial team or planning personal outdoor activities.
            </p>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
            <div className="p-8 rounded-2xl bg-card border border-border hover:shadow-lg transition">
              <div className="w-14 h-14 rounded-xl bg-primary/10 flex items-center justify-center mb-6">
                <Zap className="w-7 h-7 text-primary" />
              </div>
              <h3 className="text-2xl font-bold text-foreground mb-4">Scheduling for Commercial Operations</h3>
              <ul className="space-y-3 mb-6">
                {["Multi-task scheduling with optimal time windows", "Manage simultaneous projects across multiple locations",
                  "Worker safety compliance and heat index monitoring", "Detailed analytics and reporting dashboards"].map((item) => (
                  <li key={item} className="flex items-start gap-3">
                    <span className="text-primary font-bold mt-0.5">-</span>
                    <span className="text-muted-foreground">{item}</span>
                  </li>
                ))}
              </ul>
              <p className="text-sm text-muted-foreground">
                Perfect for construction crews, maintenance teams, outdoor event planners.
              </p>
            </div>
            <div className="p-8 rounded-2xl bg-card border border-border hover:shadow-lg transition">
              <div className="w-14 h-14 rounded-xl bg-secondary/10 flex items-center justify-center mb-6">
                <Navigation className="w-7 h-7 text-secondary" />
              </div>
              <h3 className="text-2xl font-bold text-foreground mb-4">Navigation for Personal Activities</h3>
              <ul className="space-y-3 mb-6">
                {["Plan outdoor activities with UV exposure awareness", "Find shaded routes for walking, jogging, or cycling",
                  "Real-time heat and sun exposure alerts", "Personalized recommendations for outdoor timing"].map((item) => (
                  <li key={item} className="flex items-start gap-3">
                    <span className="text-secondary font-bold mt-0.5">-</span>
                    <span className="text-muted-foreground">{item}</span>
                  </li>
                ))}
              </ul>
              <p className="text-sm text-muted-foreground">
                Ideal for fitness enthusiasts, outdoor photographers, and everyday navigators.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Pricing Section */}
      <section id="pricing" className="py-12 sm:py-24 border-t border-border">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center space-y-4 mb-12">
            <h2 className="text-3xl sm:text-4xl font-bold text-foreground">Simple Pricing</h2>
            <p className="text-lg text-muted-foreground max-w-2xl mx-auto">
              Personal use is free. Commercial plans for teams that need advanced scheduling.
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8 max-w-5xl mx-auto">
            <div className="rounded-2xl border border-border bg-card p-8 shadow-sm flex flex-col">
              <h3 className="text-xl font-bold text-foreground mb-1">Personal</h3>
              <p className="text-sm text-muted-foreground mb-4">For individuals</p>
              <div className="text-4xl font-bold text-primary mb-6">Free</div>
              <ul className="space-y-3 mb-8 flex-1">
                {["Shade-optimized route navigation", "Real-time sun tracking", "UV and heat risk alerts", "Save favorite places"].map((f) => (
                  <li key={f} className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Check className="w-4 h-4 text-green-500 shrink-0" />
                    {f}
                  </li>
                ))}
              </ul>
              <Link to="/register">
                <Button variant="outline" className="w-full">Get Started</Button>
              </Link>
            </div>
            <div className="rounded-2xl border-2 border-primary bg-card p-8 shadow-lg flex flex-col relative">
              <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-1 bg-primary text-primary-foreground text-xs font-bold rounded-full">
                Most Popular
              </div>
              <h3 className="text-xl font-bold text-foreground mb-1">Commercial</h3>
              <p className="text-sm text-muted-foreground mb-4">For teams & businesses</p>
              <div className="text-4xl font-bold text-primary mb-1">$29</div>
              <p className="text-sm text-muted-foreground mb-6">per month</p>
              <ul className="space-y-3 mb-8 flex-1">
                {["Everything in Personal", "Task scheduling & analytics", "Team management dashboard", "Polygon area analysis",
                  "Shadow schedule optimization", "Priority support"].map((f) => (
                  <li key={f} className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Check className="w-4 h-4 text-green-500 shrink-0" />
                    {f}
                  </li>
                ))}
              </ul>
              <Link to="/register">
                <Button className="w-full bg-primary hover:bg-primary/90 text-primary-foreground">Start Free Trial</Button>
              </Link>
            </div>
            <div className="rounded-2xl border border-border bg-card p-8 shadow-sm flex flex-col">
              <h3 className="text-xl font-bold text-foreground mb-1">Enterprise</h3>
              <p className="text-sm text-muted-foreground mb-4">Custom solutions</p>
              <div className="text-4xl font-bold text-primary mb-6">Custom</div>
              <ul className="space-y-3 mb-8 flex-1">
                {["Everything in Commercial", "Custom API integrations", "Dedicated account manager", "SLA guarantees", "On-premise deployment"].map((f) => (
                  <li key={f} className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Check className="w-4 h-4 text-green-500 shrink-0" />
                    {f}
                  </li>
                ))}
              </ul>
              <a href="#contact">
                <Button variant="outline" className="w-full">Contact Sales</Button>
              </a>
            </div>
          </div>
        </div>
      </section>

      {/* Contact Section */}
      <section id="contact" className="py-12 sm:py-24 border-t border-border bg-card/30">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center space-y-4 mb-12">
            <h2 className="text-3xl sm:text-4xl font-bold text-foreground">Get in Touch</h2>
            <p className="text-lg text-muted-foreground max-w-2xl mx-auto">
              Have questions or need a custom solution? We'd love to hear from you.
            </p>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 max-w-5xl mx-auto">
            <div className="space-y-6">
              <div className="flex items-start gap-4">
                <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                  <Mail className="w-5 h-5 text-primary" />
                </div>
                <div>
                  <h3 className="font-semibold text-foreground">Email</h3>
                  <p className="text-sm text-muted-foreground">contact@smartshift.io</p>
                </div>
              </div>
              <div className="flex items-start gap-4">
                <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                  <Phone className="w-5 h-5 text-primary" />
                </div>
                <div>
                  <h3 className="font-semibold text-foreground">Phone</h3>
                  <p className="text-sm text-muted-foreground">+971 4 123 4567</p>
                </div>
              </div>
              <div className="flex items-start gap-4">
                <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                  <MapPin className="w-5 h-5 text-primary" />
                </div>
                <div>
                  <h3 className="font-semibold text-foreground">Office</h3>
                  <p className="text-sm text-muted-foreground">Dubai Internet City, Dubai, UAE</p>
                </div>
              </div>
            </div>
            <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); alert("Message sent! We'll get back to you soon."); }}>
              <div className="grid grid-cols-2 gap-4">
                <input type="text" placeholder="First Name" required
                  className="px-4 py-3 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary" />
                <input type="text" placeholder="Last Name" required
                  className="px-4 py-3 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary" />
              </div>
              <input type="email" placeholder="Email" required
                className="w-full px-4 py-3 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary" />
              <textarea placeholder="Message" rows={4} required
                className="w-full px-4 py-3 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary resize-none" />
              <Button type="submit" className="w-full bg-primary hover:bg-primary/90 text-primary-foreground">
                Send Message
              </Button>
            </form>
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="py-12 sm:py-24 border-t border-border">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 text-center space-y-8">
          <div className="space-y-4">
            <h2 className="text-3xl sm:text-4xl font-bold text-foreground">Ready to Optimize Your Day?</h2>
            <p className="text-lg text-muted-foreground">
              Join thousands of users who are making smarter decisions about outdoor work and activities.
            </p>
          </div>
          <div className="flex flex-col sm:flex-row gap-4 justify-center">
            <Link to="/map" onClick={() => setMode("commercial")}>
              <Button size="lg" className="bg-primary hover:bg-primary/90 text-primary-foreground gap-2">
                <CalendarClock className="w-5 h-5" />
                Schedule Tasks
              </Button>
            </Link>
            <Link to="/map" onClick={handlePersonalClick}>
              <Button size="lg" variant="outline" className="gap-2">
                <Route className="w-5 h-5" />
                Navigate Routes
              </Button>
            </Link>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-border py-8 bg-card/30">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex flex-col sm:flex-row justify-between items-center gap-4 text-sm text-muted-foreground">
            <span>2025 ShadeMe. All rights reserved.</span>
            <div className="flex gap-6">
              <a className="hover:text-foreground transition cursor-pointer">Privacy</a>
              <a className="hover:text-foreground transition cursor-pointer">Terms</a>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
