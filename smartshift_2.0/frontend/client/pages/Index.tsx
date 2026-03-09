import { Link } from "react-router-dom";
import { Sun, Cloud, Navigation, Clock, Map, Moon, Target, CloudSun, Cpu, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useDarkMode } from "../hooks/use-dark-mode";

export default function Index() {
  const { isDark, toggle: toggleDarkMode } = useDarkMode();

  return (
    <div className="min-h-screen bg-gradient-to-br from-background via-background to-slate-50 dark:from-background dark:via-background dark:to-slate-900">
      {/* Navigation */}
      <nav className="sticky top-0 z-50 backdrop-blur-md bg-background/80 dark:bg-background/80 border-b border-border">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-primary to-amber-400 flex items-center justify-center">
                <Sun className="w-6 h-6 text-primary-foreground" />
              </div>
              <span className="text-xl font-bold text-foreground">SmartShift</span>
            </div>
            <div className="hidden md:flex items-center gap-4">
              <a href="#" className="text-sm font-medium text-muted-foreground hover:text-foreground transition">
                Overview
              </a>
              <a href="#about" className="text-sm font-medium text-muted-foreground hover:text-foreground transition">
                About
              </a>
              <a href="#product" className="text-sm font-medium text-muted-foreground hover:text-foreground transition">
                Product
              </a>
              <a href="#solutions" className="text-sm font-medium text-muted-foreground hover:text-foreground transition">
                Solutions
              </a>
              <a href="#pricing" className="text-sm font-medium text-muted-foreground hover:text-foreground transition">
                Pricing
              </a>
              <a href="#contact" className="text-sm font-medium text-muted-foreground hover:text-foreground transition">
                Contact
              </a>
              <button
                onClick={toggleDarkMode}
                className="p-2 hover:bg-secondary/20 rounded-lg transition"
                title={isDark ? "Switch to light mode" : "Switch to dark mode"}
              >
                {isDark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
              </button>
              <Link to="/login">
                <Button size="sm" variant="outline">
                  Sign In
                </Button>
              </Link>
              <Link to="/register">
                <Button size="sm" className="bg-primary hover:bg-primary/90 text-primary-foreground">
                  Get Started
                </Button>
              </Link>
            </div>
            <div className="md:hidden flex items-center gap-2">
              <button
                onClick={toggleDarkMode}
                className="p-2 hover:bg-secondary/20 rounded-lg transition"
                title={isDark ? "Switch to light mode" : "Switch to dark mode"}
              >
                {isDark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
              </button>
              <Link to="/register">
                <Button size="sm" className="bg-primary hover:bg-primary/90 text-primary-foreground">
                  Start
                </Button>
              </Link>
            </div>
          </div>
        </div>
      </nav>

      {/* Hero Section */}
      <section className="relative overflow-hidden pt-12 pb-20 sm:pt-16 sm:pb-24">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 items-center">
            {/* Left Content */}
            <div className="space-y-8">
              <div className="space-y-4">
                <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-primary/10 text-primary border border-primary/20">
                  <span className="text-sm font-semibold">Real-Time Shade Intelligence</span>
                </div>
                <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold text-foreground tracking-tight">
                  Optimize Your Outdoor Work
                </h1>
                <p className="text-lg sm:text-xl text-muted-foreground max-w-xl">
                  SmartShift predicts shadow patterns, schedules tasks efficiently, and routes you through the safest, coolest paths. Protect yourself from excessive sun exposure while maximizing productivity.
                </p>
              </div>

              <div className="flex flex-col sm:flex-row gap-4">
                <Link to="/dashboard">
                  <Button size="lg" className="w-full sm:w-auto bg-primary hover:bg-primary/90 text-primary-foreground">
                    Launch App
                  </Button>
                </Link>
                <a href="#about">
                  <Button size="lg" variant="outline" className="w-full sm:w-auto">
                    Learn More
                  </Button>
                </a>
              </div>

              {/* Stats */}
              <div className="grid grid-cols-3 gap-4 pt-8">
                <div>
                  <div className="text-2xl font-bold text-primary">3D</div>
                  <p className="text-sm text-muted-foreground">Urban Mapping</p>
                </div>
                <div>
                  <div className="text-2xl font-bold text-secondary">360°</div>
                  <p className="text-sm text-muted-foreground">Sun Tracking</p>
                </div>
                <div>
                  <div className="text-2xl font-bold text-accent">Real-Time</div>
                  <p className="text-sm text-muted-foreground">Updates</p>
                </div>
              </div>
            </div>

            {/* Right Visual */}
            <div className="relative h-96 sm:h-full flex items-center justify-center">
              <div className="absolute inset-0 bg-gradient-to-r from-primary/20 to-secondary/20 rounded-3xl blur-3xl"></div>
              <div className="relative bg-gradient-to-br from-primary/5 to-secondary/5 backdrop-blur rounded-3xl p-12 border border-border shadow-2xl">
                <div className="space-y-4">
                  <div className="flex items-center gap-4 p-4 rounded-xl bg-background/50 border border-border">
                    <Sun className="w-8 h-8 text-primary" />
                    <div className="flex-1">
                      <p className="text-sm font-semibold text-foreground">Sun Position</p>
                      <p className="text-xs text-muted-foreground">45° NE, UV Index: 8</p>
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
                      <p className="text-xs text-muted-foreground">2.3 km • 15 min • 80% shaded</p>
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
            SmartShift is a real-time shade tracking and scheduling platform designed to help people
            navigate cities while minimizing exposure to direct sunlight.
            By combining 3D city models, solar movement calculations, and dynamic routing,
            the system identifies shaded paths and optimal schedules throughout the day.
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
            <div className="p-6 rounded-2xl bg-card border border-border hover:border-primary/30 transition">
              <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center mb-4">
                <Target className="w-6 h-6 text-primary" />
              </div>
              <h3 className="text-lg font-semibold text-foreground mb-2">Our Mission</h3>
              <p className="text-sm text-muted-foreground">
              Our mission is to make urban environments more comfortable and accessible by helping
              companies and individuals avoid excessive sunlight.
              We aim to provide a smarter way to plan routes and schedules based on shade availability.
              </p>
            </div>
            <div className="p-6 rounded-2xl bg-card border border-border hover:border-primary/30 transition">
              <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center mb-4">
                <CloudSun className="w-6 h-6 text-primary" />
              </div>
              <h3 className="text-lg font-semibold text-foreground mb-2">The Problem We Address</h3>
              <p className="text-sm text-muted-foreground">
              Pedestrians and outdoor workers are exposed to intense sunlight throughout the day.
              Traditional systems ignore environmental factors such as sun exposure duration while scheduling
              tasks and suggesting routes.
              We address this gap by incorporating solar positioning and building geometry to generate
              routes and schedules that reduce sun exposure.
              </p>
            </div>
            <div className="p-6 rounded-2xl bg-card border border-border hover:border-primary/30 transition">
              <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center mb-4">
                <Cpu className="w-6 h-6 text-primary" />
              </div>
              <h3 className="text-lg font-semibold text-foreground mb-2">Technology</h3>
              <p className="text-sm text-muted-foreground">
              Integrates solar position algorithms, 3D city modeling, and real-time scheduling systems to
              compute shaded routes and time-optimized navigation. The platform uses ML to generate
              dynamic recommendations through an interactive dashboard and learns over time.
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
            <p className="text-lg text-muted-foreground max-w-2xl mx-auto">
              Advanced technology to keep you safe and productive.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
            {/* Feature 1 */}
            <div className="p-6 rounded-2xl bg-card border border-border hover:border-primary/30 transition">
              <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center mb-4">
                <Map className="w-6 h-6 text-primary" />
              </div>
              <h3 className="text-lg font-semibold text-foreground mb-2">3D Urban Mapping</h3>
              <p className="text-sm text-muted-foreground">
                Real-time 3D urban models with Mapbox integration for accurate shadow prediction
              </p>
            </div>

            {/* Feature 2 */}
            <div className="p-6 rounded-2xl bg-card border border-border hover:border-secondary/30 transition">
              <div className="w-12 h-12 rounded-lg bg-secondary/10 flex items-center justify-center mb-4">
                <Sun className="w-6 h-6 text-secondary" />
              </div>
              <h3 className="text-lg font-semibold text-foreground mb-2">Sun Movement Tracking</h3>
              <p className="text-sm text-muted-foreground">
                Advanced calculations predict shadow patterns and sun exposure throughout the day
              </p>
            </div>

            {/* Feature 3 */}
            <div className="p-6 rounded-2xl bg-card border border-border hover:border-accent/30 transition">
              <div className="w-12 h-12 rounded-lg bg-accent/10 flex items-center justify-center mb-4">
                <Clock className="w-6 h-6 text-accent" />
              </div>
              <h3 className="text-lg font-semibold text-foreground mb-2">Smart Scheduling</h3>
              <p className="text-sm text-muted-foreground">
                Optimize task timing based on minimum sun exposure and maximum shade coverage
              </p>
            </div>

            {/* Feature 4 */}
            <div className="p-6 rounded-2xl bg-card border border-border hover:border-primary/30 transition">
              <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center mb-4">
                <Navigation className="w-6 h-6 text-primary" />
              </div>
              <h3 className="text-lg font-semibold text-foreground mb-2">Heat-Optimized Routing</h3>
              <p className="text-sm text-muted-foreground">
                Routes that minimize sun exposure with alternate path suggestions
              </p>
            </div>

            {/* Feature 5 */}
            <div className="p-6 rounded-2xl bg-card border border-border hover:border-secondary/30 transition">
              <div className="w-12 h-12 rounded-lg bg-secondary/10 flex items-center justify-center mb-4">
                <Zap className="w-6 h-6 text-secondary" />
              </div>
              <h3 className="text-lg font-semibold text-foreground mb-2">Real-Time Alerts</h3>
              <p className="text-sm text-muted-foreground">
                Instant notifications when heat levels reach dangerous thresholds
              </p>
            </div>

            {/* Feature 6 */}
            <div className="p-6 rounded-2xl bg-card border border-border hover:border-accent/30 transition">
              <div className="w-12 h-12 rounded-lg bg-accent/10 flex items-center justify-center mb-4">
                <Cloud className="w-6 h-6 text-accent" />
              </div>
              <h3 className="text-lg font-semibold text-foreground mb-2">Weather Integration</h3>
              <p className="text-sm text-muted-foreground">
                Real-time and forecasted heat data for accurate risk assessment
              </p>
            </div>
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
            {/* Commercial Use Case */}
            <div className="p-8 rounded-2xl bg-card border border-border hover:shadow-lg transition">
              <div className="w-14 h-14 rounded-xl bg-primary/10 flex items-center justify-center mb-6">
                <Zap className="w-7 h-7 text-primary" />
              </div>
              <h3 className="text-2xl font-bold text-foreground mb-4">Scheduling for Commercial Operations</h3>
              <ul className="space-y-3 mb-6">
                <li className="flex items-start gap-3">
                  <span className="text-primary font-bold mt-0.5">→</span>
                  <span className="text-muted-foreground">Multi-task scheduling with optimal time windows</span>
                </li>
                <li className="flex items-start gap-3">
                  <span className="text-primary font-bold mt-0.5">→</span>
                  <span className="text-muted-foreground">Manage simultaneous projects across multiple locations</span>
                </li>
                <li className="flex items-start gap-3">
                  <span className="text-primary font-bold mt-0.5">→</span>
                  <span className="text-muted-foreground">Worker safety compliance and heat index monitoring</span>
                </li>
                <li className="flex items-start gap-3">
                  <span className="text-primary font-bold mt-0.5">→</span>
                  <span className="text-muted-foreground">Detailed analytics and reporting dashboards</span>
                </li>
              </ul>
              <p className="text-sm text-muted-foreground">
                Perfect for construction crews, maintenance teams, outdoor event planners, and any commercial operation that works under the sun.
              </p>
            </div>

            {/* Personal Use Case */}
            <div className="p-8 rounded-2xl bg-card border border-border hover:shadow-lg transition">
              <div className="w-14 h-14 rounded-xl bg-secondary/10 flex items-center justify-center mb-6">
                <Navigation className="w-7 h-7 text-secondary" />
              </div>
              <h3 className="text-2xl font-bold text-foreground mb-4">Navigation for Personal Activities</h3>
              <ul className="space-y-3 mb-6">
                <li className="flex items-start gap-3">
                  <span className="text-secondary font-bold mt-0.5">→</span>
                  <span className="text-muted-foreground">Plan outdoor activities with UV exposure awareness</span>
                </li>
                <li className="flex items-start gap-3">
                  <span className="text-secondary font-bold mt-0.5">→</span>
                  <span className="text-muted-foreground">Find shaded routes for walking, jogging, or cycling</span>
                </li>
                <li className="flex items-start gap-3">
                  <span className="text-secondary font-bold mt-0.5">→</span>
                  <span className="text-muted-foreground">Real-time heat and sun exposure alerts</span>
                </li>
                <li className="flex items-start gap-3">
                  <span className="text-secondary font-bold mt-0.5">→</span>
                  <span className="text-muted-foreground">Personalized recommendations for outdoor timing</span>
                </li>
              </ul>
              <p className="text-sm text-muted-foreground">
                Ideal for fitness enthusiasts, outdoor photographers, navigators, and anyone who wants to enjoy the outdoors safely.
              </p>
            </div>
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
          <div className="space-y-2"/>
          <Link to="/dashboard">
            <Button size="lg" className="bg-primary hover:bg-primary/90 text-primary-foreground">
              Get Started Now!
            </Button>
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-border py-8 bg-card/30">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex flex-col sm:flex-row justify-between items-center gap-4 text-sm text-muted-foreground">
            <div className="flex items-center gap-2">
              <span>© 2024 SmartShift. All rights reserved.</span>
            </div>
            <div className="flex gap-6">
              <a className="hover:text-foreground transition">Privacy</a>
              <a className="hover:text-foreground transition">Terms</a>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
