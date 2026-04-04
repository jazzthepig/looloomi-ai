import { useScrollAnimation } from "../../hooks/useScrollAnimation";

/**
 * AnimatedCard - Reusable animated card component with hover effects
 *
 * @param {Object} props
 * @param {React.ReactNode} props.children
 * @param {string} props.variant - 'default' | 'accent' | 'glow', default 'default'
 * @param {number} props.delay - Animation delay in ms, default 0
 * @param {string} props.className - Additional CSS classes
 * @param {Object} props.style - Additional inline styles
 * @param {Function} props.onClick - Click handler
 */
export default function AnimatedCard({
  children,
  variant = "default",
  delay = 0,
  className = "",
  style = {},
  onClick,
}) {
  const { ref } = useScrollAnimation({ threshold: 0.1 });

  const variantStyles = {
    default: {
      borderColor: "rgba(37,99,235,0.14)",
      hoverBorder: "rgba(37,99,235,0.28)",
    },
    accent: {
      borderColor: "rgba(99,102,241,0.28)",
      hoverBorder: "rgba(99,102,241,0.45)",
      borderLeft: "2px solid rgba(99,102,241,0.45)",
    },
    glow: {
      borderColor: "rgba(99,102,241,0.18)",
      hoverBorder: "rgba(99,102,241,0.35)",
      hoverBoxShadow: "0 0 20px rgba(99,102,241,0.15), 0 4px 24px rgba(0,0,0,0.3)",
    },
  };

  const v = variantStyles[variant] || variantStyles.default;

  return (
    <div
      ref={ref}
      className={`lm-card transition-lift ${className}`}
      style={{
        borderColor: v.borderColor,
        borderLeft: v.borderLeft,
        animationDelay: `${delay}ms`,
        transition: "transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease",
        cursor: onClick ? "pointer" : "default",
        ...style,
      }}
      onClick={onClick}
      onMouseEnter={(e) => {
        if (v.hoverBorder) e.currentTarget.style.borderColor = v.hoverBorder;
        if (v.hoverBoxShadow) e.currentTarget.style.boxShadow = v.hoverBoxShadow;
        if (v.borderLeft && variant === "accent") {
          e.currentTarget.style.borderLeftColor = "rgba(99,102,241,0.6)";
        }
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = v.borderColor;
        e.currentTarget.style.boxShadow = "";
        if (v.borderLeft && variant === "accent") {
          e.currentTarget.style.borderLeftColor = "rgba(99,102,241,0.45)";
        }
      }}
    >
      {children}
    </div>
  );
}
