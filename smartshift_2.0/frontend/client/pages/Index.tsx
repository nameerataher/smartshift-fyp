import { Link } from "react-router-dom";
import { Cloud, Map, CheckSquare, Navigation2, AlertTriangle, Clock, Briefcase, Navigation, Shield } from "lucide-react";

export default function Index() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Navigation */}
      <header className="sticky top-0 z-50 border-b border-border bg-card/80 backdrop-blur-sm shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-gradient-to-br from-primary to-accent rounded-lg flex items-center justify-center shadow-md">
              <Cloud className="w-6 h-6 text-primary-foreground" />
            </div>
            <span className="text-xl font-bold">SmartShift</span>
          </div>
          <Link
            to="/dashboard"
            className="px-6 py-2 bg-primary text-primary-foreground rounded-lg font-medium hover:bg-primary/90 transition-colors"
          >
            Launch App
          </Link>
        </div>
      </header>

      {/* Hero Section */}
      <section className="relative overflow-hidden">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-20 sm:py-32">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 items-center">
            {/* Content */}
            <div className="space-y-8">
              <div className="space-y-4">
                <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold leading-tight">
                  Optimize Shifts,{" "}
                  <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
                    Minimize Heat Exposure
                  </span>
                </h1>
                <p className="text-lg text-muted-foreground leading-relaxed">
                  Real-time shade tracking with 3D urban mapping and heat forecasting.
                  Determine optimal schedules, routes, and timings to protect outdoor workers.
                </p>
              </div>

              <div className="flex flex-col sm:flex-row gap-4">
                <Link
                  to="/dashboard"
                  className="px-8 py-4 bg-primary text-primary-foreground rounded-lg font-semibold hover:bg-primary/90 transition-all shadow-lg hover:shadow-xl text-center"
                >
                  View Dashboard
                </Link>
                <Link
                  to="/map"
                  className="px-8 py-4 border-2 border-primary text-primary rounded-lg font-semibold hover:bg-primary/10 transition-all text-center"
                >
                  Shade Map
                </Link>
              </div>

              {/* Mode badges */}
              <div className="flex gap-3 pt-2">
                <div className="flex items-center gap-2 px-4 py-2 bg-primary/10 border border-primary/20 rounded-lg">
                  <Briefcase className="w-4 h-4 text-primary" />
                  <span className="text-sm font-medium text-primary">Commercial Mode</span>
                </div>
                <div className="flex items-center gap-2 px-4 py-2 bg-muted border border-border rounded-lg">
                  <Navigation className="w-4 h-4 text-muted-foreground" />
                  <span className="text-sm font-medium text-muted-foreground">Personal Mode</span>
                </div>
              </div>

              {/* Stats */}
              <div className="grid grid-cols-3 gap-4 pt-8 border-t border-border">
                <div>
                  <p className="text-3xl font-bold text-primary">3D Maps</p>
                  <p className="text-sm text-muted-foreground">Urban Structures</p>
                </div>
                <div>
                  <p className="text-3xl font-bold text-primary">Live Heat</p>
                  <p className="text-sm text-muted-foreground">& UV Data</p>
                </div>
                <div>
                  <p className="text-3xl font-bold text-primary">Safety</p>
                  <p className="text-sm text-muted-foreground">Alerts</p>
                </div>
              </div>
            </div>

            {/* Visual */}
            <div className="relative h-96 lg:h-full min-h-96">
              <div className="absolute inset-0 bg-gradient-to-br from-primary/20 to-accent/20 rounded-3xl blur-3xl" />
              <div className="relative h-full bg-gradient-to-br from-primary/10 via-background to-accent/10 rounded-3xl border border-border shadow-2xl overflow-hidden p-8 flex items-center justify-center">
                <div className="w-full h-full flex items-center justify-center">
                  <div className="relative w-64 h-64">
                    {/* Animated sun */}
                    <div className="absolute -top-8 right-0 w-14 h-14 bg-gradient-to-br from-primary to-accent rounded-full shadow-lg animate-pulse flex items-center justify-center">
                      <Cloud className="w-7 h-7 text-white" />
                    </div>
                    {/* Buildings */}
                    <div className="absolute bottom-16 left-8 w-20 h-32 bg-gradient-to-t from-primary/40 to-primary/20 border border-primary/50 rounded-lg shadow-xl">
                      <div className="absolute -bottom-8 left-0 right-0 h-8 bg-gradient-to-r from-accent/60 to-transparent rounded-b-lg" />
                    </div>
                    <div className="absolute bottom-16 right-8 w-24 h-40 bg-gradient-to-t from-accent/40 to-accent/20 border border-accent/50 rounded-lg shadow-xl">
                      <div className="absolute -bottom-12 left-0 right-0 h-12 bg-gradient-to-r from-accent/70 to-transparent rounded-b-lg" />
                    </div>
                    {/* Stats badge */}
                    <div className="absolute -bottom-4 left-1/2 transform -translate-x-1/2 px-4 py-2 bg-primary/20 border border-primary/40 rounded-full text-xs font-semibold text-primary whitespace-nowrap">
                      UV: 8.5 | Heat: 42°C
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section className="border-t border-border bg-card/30">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-20 sm:py-32">
          <div className="text-center mb-16">
            <h2 className="text-3xl sm:text-4xl font-bold mb-4">Protect Your Workforce</h2>
            <p className="text-lg text-muted-foreground max-w-2xl mx-auto">
              Advanced shade tracking and shift optimization for safe, efficient outdoor work
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
            {[
              {
                icon: Cloud,
                title: "Real-time Shade Tracking",
                desc: "Monitor shaded areas dynamically using 3D urban structure mapping and real-time sun movement calculations.",
              },
              {
                icon: AlertTriangle,
                title: "Heat & UV Exposure",
                desc: "Visual metrics showing real-time and forecasted heat levels with UV exposure indicators for worker safety.",
              },
              {
                icon: Clock,
                title: "Optimal Shift Scheduling",
                desc: "AI-powered recommendations for ideal work schedules that minimize direct sun exposure and heat stress.",
              },
              {
                icon: Navigation2,
                title: "Smart Route Optimization",
                desc: "Get optimal routes and timings for navigation that prioritize shaded paths and cooler conditions.",
              },
              {
                icon: CheckSquare,
                title: "Activity Recommendations",
                desc: "Real-time suggestions for outdoor activities and work tasks based on current and predicted heat conditions.",
              },
              {
                icon: Shield,
                title: "Safety Alerts & Notifications",
                desc: "Automatic alerts when heat levels become dangerous with immediate recommendations for worker protection.",
              },
            ].map(({ icon: Icon, title, desc }) => (
              <div key={title} className="bg-card border border-border rounded-2xl p-8 shadow-sm hover:shadow-md transition-shadow">
                <div className="w-12 h-12 bg-primary/10 rounded-lg flex items-center justify-center mb-4">
                  <Icon className="w-6 h-6 text-primary" />
                </div>
                <h3 className="text-xl font-semibold mb-3 text-foreground">{title}</h3>
                <p className="text-muted-foreground">{desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="border-t border-border">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-20 sm:py-32 text-center">
          <h2 className="text-3xl sm:text-4xl font-bold mb-6">Ensure Worker Safety Today</h2>
          <p className="text-lg text-muted-foreground mb-8 max-w-2xl mx-auto">
            Join construction companies, delivery services, and outdoor teams using SmartShift
            to protect workers from heat and UV exposure.
          </p>
          <Link
            to="/dashboard"
            className="inline-block px-8 py-4 bg-primary text-primary-foreground rounded-lg font-semibold hover:bg-primary/90 transition-all shadow-lg hover:shadow-xl"
          >
            Get Started Now
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-border bg-card/30 py-8">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Cloud className="w-5 h-5 text-primary" />
            <span className="font-semibold">SmartShift</span>
          </div>
          <p className="text-sm text-muted-foreground">
            Real-time shade tracking & shift optimization © 2025
          </p>
        </div>
      </footer>
    </div>
  );
}
