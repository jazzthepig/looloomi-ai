import { useEffect, useRef } from "react";

/**
 * useScrollAnimation - triggers visibility-based animations when elements enter viewport
 *
 * @param {Object} options
 * @param {number} options.threshold - Intersection ratio to trigger (0-1), default 0.1
 * @param {boolean} options.once - Only trigger once, default true
 * @param {string} options.rootMargin - Margin around root, default "0px"
 * @returns {Object} { ref, isVisible }
 */
export function useScrollAnimation({
  threshold = 0.1,
  once = true,
  rootMargin = "0px",
} = {}) {
  const ref = useRef(null);
  const isVisible = useRef(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            isVisible.current = true;
            el.classList.add("animate-visible");
            if (once) {
              observer.unobserve(el);
            }
          } else if (!once) {
            isVisible.current = false;
            el.classList.remove("animate-visible");
          }
        });
      },
      { threshold, rootMargin }
    );

    // Start with animate-on-scroll class
    el.classList.add("animate-on-scroll");

    observer.observe(el);

    return () => observer.disconnect();
  }, [threshold, once, rootMargin]);

  return { ref, isVisible: isVisible.current };
}

/**
 * useStaggerAnimation - applies staggered animation delays to children
 *
 * @param {Object} options
 * @param {number} options.threshold - Intersection ratio to trigger, default 0.1
 * @param {number} options.baseDelay - Base delay in ms, default 50
 * @param {number} options.step - Delay increment per child in ms, default 50
 * @returns {Object} { containerRef }
 */
export function useStaggerAnimation({
  threshold = 0.1,
  baseDelay = 50,
  step = 50,
} = {}) {
  const containerRef = useRef(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const children = container.querySelectorAll(".stagger-child");

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            children.forEach((child, i) => {
              setTimeout(() => {
                child.classList.add("animate-visible");
              }, i * step);
            });
            observer.unobserve(container);
          }
        });
      },
      { threshold }
    );

    observer.observe(container);

    return () => observer.disconnect();
  }, [threshold, baseDelay, step]);

  return { containerRef };
}
