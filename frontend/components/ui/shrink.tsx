"use client";

import type { Transition } from "motion/react";
import { motion, useAnimation } from "motion/react";
import type { HTMLAttributes } from "react";
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef } from "react";

import { cn } from "@/lib/utils";

export interface ShrinkIconHandle {
  startAnimation: () => void;
  stopAnimation: () => void;
}

interface ShrinkIconProps extends HTMLAttributes<HTMLDivElement> {
  size?: number;
}

const DEFAULT_TRANSITION: Transition = {
  type: "spring",
  stiffness: 250,
  damping: 25,
};

const ShrinkIcon = forwardRef<ShrinkIconHandle, ShrinkIconProps>(
  ({ onMouseEnter, onMouseLeave, className, size = 28, ...props }, ref) => {
    const controls = useAnimation();
    const isControlledRef = useRef(false);
    const wrapperRef = useRef<HTMLDivElement>(null);

    useImperativeHandle(ref, () => {
      isControlledRef.current = true;

      return {
        startAnimation: () => controls.start("animate"),
        stopAnimation: () => controls.start("normal"),
      };
    });
    // Listen to parent hover events for icons inside buttons
    useEffect(() => {
      if (isControlledRef.current) return;

      const wrapper = wrapperRef.current;
      if (!wrapper) return;

      const parent = wrapper.closest('button, a, [role="button"]');
      if (!parent || parent === wrapper) return;

      const handleParentEnter = () => controls.start("animate");
      const handleParentLeave = () => controls.start("normal");

      parent.addEventListener("mouseenter", handleParentEnter);
      parent.addEventListener("mouseleave", handleParentLeave);

      return () => {
        parent.removeEventListener("mouseenter", handleParentEnter);
        parent.removeEventListener("mouseleave", handleParentLeave);
      };
    }, [controls]);
const handleMouseEnter = useCallback(
      (e: React.MouseEvent<HTMLDivElement>) => {
        if (isControlledRef.current) {
          onMouseEnter?.(e);
        } else {
          controls.start("animate");
        }
      },
      [controls, onMouseEnter]
    );

    const handleMouseLeave = useCallback(
      (e: React.MouseEvent<HTMLDivElement>) => {
        if (isControlledRef.current) {
          onMouseLeave?.(e);
        } else {
          controls.start("normal");
        }
      },
      [controls, onMouseLeave]
    );

    return (
      <div
        ref={wrapperRef}
        className={cn("pointer-events-auto", className)}
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
        {...props}
      >
        <svg
          fill="none"
          height={size}
          stroke="currentColor"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="2"
          viewBox="0 0 24 24"
          width={size}
          xmlns="http://www.w3.org/2000/svg"
        >
          <motion.path
            animate={controls}
            d="M9 4.2V9m0 0H4.2M9 9 3 3"
            transition={DEFAULT_TRANSITION}
            variants={{
              normal: { translateX: "0%", translateY: "0%" },
              animate: { translateX: "1px", translateY: "1px" },
            }}
          />
          <motion.path
            animate={controls}
            d="M15 4.2V9m0 0h4.8M15 9l6-6"
            transition={DEFAULT_TRANSITION}
            variants={{
              normal: { translateX: "0%", translateY: "0%" },
              animate: { translateX: "-1px", translateY: "1px" },
            }}
          />
          <motion.path
            animate={controls}
            d="M9 19.8V15m0 0H4.2M9 15l-6 6"
            transition={DEFAULT_TRANSITION}
            variants={{
              normal: { translateX: "0%", translateY: "0%" },
              animate: { translateX: "1px", translateY: "-1px" },
            }}
          />
          <motion.path
            animate={controls}
            d="m15 15 6 6m-6-6v4.8m0-4.8h4.8"
            transition={DEFAULT_TRANSITION}
            variants={{
              normal: { translateX: "0%", translateY: "0%" },
              animate: { translateX: "-1px", translateY: "-1px" },
            }}
          />
        </svg>
      </div>
    );
  }
);

ShrinkIcon.displayName = "ShrinkIcon";

export { ShrinkIcon };
