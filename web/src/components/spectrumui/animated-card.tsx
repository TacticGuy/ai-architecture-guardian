/**
 * Technology card: Spectrum UI TiltCard (3D pointer tilt, glare and depth parallax) with a staggered scroll-in
 * entrance. Replaces the registry AnimatedCard, whose logo slot depends on next/image.
 */
import { motion } from "framer-motion";
import type { ReactNode } from "react";

import { TiltCard, TiltCardItem } from "@/components/spectrumui/tilt-card";
import { useTheme } from "@/lib/theme";

export function AnimatedCard({
  icon, title, aboutProduct, index = 0,
}: { icon: ReactNode; title: string; aboutProduct: string; index?: number }) {
  const { theme } = useTheme();
  return (
    <motion.div
      initial={{ opacity: 0, y: 18 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-40px" }}
      transition={{ duration: 0.5, delay: (index % 3) * 0.07, ease: [0.22, 1, 0.36, 1] }}
      className="h-full"
    >
      <TiltCard
        maxTilt={10}
        scale={1.03}
        glareColor={theme === "dark" ? "rgba(255, 255, 255, 0.14)" : "rgba(0, 0, 0, 0.07)"}
        containerClassName="h-full"
        className="h-full"
      >
        <div className="flex h-full flex-col items-center p-6">
          <TiltCardItem depth={40}>
            <div className="mb-4 flex size-16 items-center justify-center rounded-2xl border border-border bg-background text-foreground">
              {icon}
            </div>
          </TiltCardItem>
          <div className="space-y-1 text-center">
            <TiltCardItem depth={28}>
              <div className="text-lg font-semibold tracking-tight text-foreground">{title}</div>
            </TiltCardItem>
            <TiltCardItem depth={14}>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">{aboutProduct}</p>
            </TiltCardItem>
          </div>
        </div>
      </TiltCard>
    </motion.div>
  );
}
