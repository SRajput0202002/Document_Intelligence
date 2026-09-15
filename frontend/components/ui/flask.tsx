"use client";

import type { Variants } from "motion/react";
import { motion, useAnimation } from "motion/react";
import type { HTMLAttributes } from "react";
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef } from "react";

import { cn } from "@/lib/utils";

export interface FlaskIconHandle {
  startAnimation: () => void;
  stopAnimation: () => void;
}

interface FlaskIconProps extends HTMLAttributes<HTMLDivElement> {
  size?: number;
}

const FLASK_VARIANTS: Variants = {
  visible: { opacity: 1 },
  hidden: { opacity: 1 },
};

const LIQUID_VARIANTS: Variants = {
  visible: { y: 0, opacity: 1 },
  animate: { y: [-2, 2, -2], opacity: 1 },
};

const BUBBLE_VARIANTS: Variants = {
  visible: { y: 0, opacity: 0.5 },
  animate: { y: [-3, -6, -3], opacity: [0.5, 1, 0.5] },
};

const FlaskIcon = forwardRef<FlaskIconHandle, FlaskIconProps>(
  ({ onMouseEnter, onMouseLeave, className, size = 28, ...props }, ref) => {
    const controls = useAnimation();
    const isControlledRef = useRef(false);
    const wrapperRef = useRef<HTMLDivElement>(null);

    useImperativeHandle(ref, () => {
      isControlledRef.current = true;

      return {
        startAnimation: async () => {
          await controls.start("animate");
        },
        stopAnimation: () => controls.start("visible"),
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
      const handleParentLeave = () => controls.start("visible");

      parent.addEventListener("mouseenter", handleParentEnter);
      parent.addEventListener("mouseleave", handleParentLeave);

      return () => {
        parent.removeEventListener("mouseenter", handleParentEnter);
        parent.removeEventListener("mouseleave", handleParentLeave);
      };
    }, [controls]);

    const handleMouseEnter = useCallback(
      async (e: React.MouseEvent<HTMLDivElement>) => {
        if (isControlledRef.current) {
          onMouseEnter?.(e);
        } else {
          await controls.start("animate");
        }
      },
      [controls, onMouseEnter]
    );

    const handleMouseLeave = useCallback(
      (e: React.MouseEvent<HTMLDivElement>) => {
        if (isControlledRef.current) {
          onMouseLeave?.(e);
        } else {
          controls.start("visible");
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
          {/* Flask outline */}
          <motion.path
            d="M10 2v7.527a2 2 0 0 1-.211.896L4.72 20.55a1 1 0 0 0 .9 1.45h12.76a1 1 0 0 0 .9-1.45l-5.069-10.127a2 2 0 0 1-.211-.896V2"
            variants={FLASK_VARIANTS}
          />
          {/* Top opening */}
          <motion.path d="M8.5 2h7" variants={FLASK_VARIANTS} />
          {/* Liquid level */}
          <motion.path
            animate={controls}
            d="M7 16h10"
            initial="visible"
            variants={LIQUID_VARIANTS}
            transition={{ duration: 0.5, repeat: Infinity, repeatType: "reverse" }}
          />
          {/* Bubbles */}
          <motion.circle
            animate={controls}
            cx="10"
            cy="18"
            r="0.5"
            fill="currentColor"
            initial="visible"
            variants={BUBBLE_VARIANTS}
            transition={{ duration: 0.6, repeat: Infinity, repeatType: "reverse", delay: 0.1 }}
          />
          <motion.circle
            animate={controls}
            cx="13"
            cy="19"
            r="0.5"
            fill="currentColor"
            initial="visible"
            variants={BUBBLE_VARIANTS}
            transition={{ duration: 0.7, repeat: Infinity, repeatType: "reverse", delay: 0.2 }}
          />
        </svg>
      </div>
    );
  }
);

FlaskIcon.displayName = "FlaskIcon";

export { FlaskIcon };
