interface LogoProps {
  className?: string;
}

export function Logo({ className = "h-10 w-auto" }: LogoProps) {
  return <img src="/logo.png" alt="ShadeMe" className={`${className} rounded-lg object-cover shrink-0`} />;
}
