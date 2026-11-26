import React from "react";
import Svg, { Circle, Path, Rect } from "react-native-svg";

import { C } from "../theme";

// Свои иконки (тонкая линия, как в iOS), чтобы не тянуть библиотеку шрифтов
export type IconName =
  | "home" | "stats" | "shield" | "book" | "user" | "back" | "chevron" | "bell" | "news" | "calendar" | "signal"
  | "trophy" | "bank" | "play" | "check" | "globe" | "wallet" | "lock" | "logout" | "trash" | "telegram" | "mail"
  | "refresh" | "chart" | "bolt" | "info" | "robot" | "edit" | "close" | "spark";

type Props = { name: IconName; size?: number; color?: string; stroke?: number };

export function Icon({ name, size = 22, color = C.text, stroke = 1.8 }: Props) {
  const p = { stroke: color, strokeWidth: stroke, fill: "none", strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  const body = (() => {
    switch (name) {
      case "home": return <><Path d="M3.5 10.5 12 3.8l8.5 6.7" {...p} /><Path d="M5.8 9v10.2h12.4V9" {...p} /><Path d="M10 19.2v-5.4h4v5.4" {...p} /></>;
      case "stats": return <><Path d="M4 19.5h16" {...p} /><Rect x="5.5" y="11" width="3" height="6" rx="1" {...p} /><Rect x="10.5" y="7" width="3" height="10" rx="1" {...p} /><Rect x="15.5" y="4" width="3" height="13" rx="1" {...p} /></>;
      case "shield": return <><Path d="M12 3.2 19 6v5.6c0 4.3-3 7.7-7 9.2-4-1.5-7-4.9-7-9.2V6z" {...p} /><Path d="m8.8 12 2.2 2.2 4.4-4.4" {...p} /></>;
      case "book": return <><Path d="M4.5 5.5c2.6-1 5.2-1 7.5.6v13c-2.3-1.6-4.9-1.6-7.5-.6z" {...p} /><Path d="M19.5 5.5c-2.6-1-5.2-1-7.5.6v13c2.3-1.6 4.9-1.6 7.5-.6z" {...p} /></>;
      case "user": return <><Circle cx="12" cy="8.3" r="3.8" {...p} /><Path d="M4.8 20c.9-3.6 3.7-5.6 7.2-5.6s6.3 2 7.2 5.6" {...p} /></>;
      case "back": return <Path d="M15 5 8 12l7 7" {...p} />;
      case "chevron": return <Path d="m9.5 6 6 6-6 6" {...p} />;
      case "close": return <><Path d="M6 6l12 12" {...p} /><Path d="M18 6 6 18" {...p} /></>;
      case "bell": return <><Path d="M6.5 16.5V11a5.5 5.5 0 0 1 11 0v5.5l1.5 1.8H5z" {...p} /><Path d="M10 20.3a2.2 2.2 0 0 0 4 0" {...p} /></>;
      case "news": return <><Rect x="3.8" y="5" width="13" height="14.5" rx="2" {...p} /><Path d="M16.8 9h2.4a1 1 0 0 1 1 1v7.5a2 2 0 0 1-2 2h-1.4" {...p} /><Path d="M7 9h6.5M7 12.5h6.5M7 16h4" {...p} /></>;
      case "calendar": return <><Rect x="4" y="5.5" width="16" height="14.5" rx="2.5" {...p} /><Path d="M4 10h16M8.5 3.5v4M15.5 3.5v4" {...p} /><Circle cx="9" cy="14.5" r=".9" fill={color} /><Circle cx="15" cy="14.5" r=".9" fill={color} /></>;
      case "signal": return <><Path d="M3.5 17 9 11.5l3.5 3.5 8-8.5" {...p} /><Path d="M15 6.5h5.5V12" {...p} /></>;
      case "trophy": return <><Path d="M7.5 4.5h9v4.8a4.5 4.5 0 0 1-9 0z" {...p} /><Path d="M7.5 6.5H4.8c0 2.6 1.2 4 3 4.3M16.5 6.5h2.7c0 2.6-1.2 4-3 4.3" {...p} /><Path d="M12 13.8v3.2M8.5 20h7M9.8 17h4.4l.8 3H9z" {...p} /></>;
      case "bank": return <><Path d="M3.8 9.5 12 4.5l8.2 5z" {...p} /><Path d="M6 10v7M10 10v7M14 10v7M18 10v7M4 19.5h16" {...p} /></>;
      case "play": return <><Circle cx="12" cy="12" r="8.5" {...p} /><Path d="m10.2 8.8 5 3.2-5 3.2z" {...p} fill={color} /></>;
      case "check": return <Path d="m5 12.5 4.5 4.5L19 7.5" {...p} />;
      case "globe": return <><Circle cx="12" cy="12" r="8.5" {...p} /><Path d="M3.5 12h17M12 3.5c2.4 2.4 3.4 5.3 3.4 8.5s-1 6.1-3.4 8.5c-2.4-2.4-3.4-5.3-3.4-8.5s1-6.1 3.4-8.5z" {...p} /></>;
      case "wallet": return <><Rect x="3.8" y="6.5" width="16.4" height="12.5" rx="2.5" {...p} /><Path d="M16 12.8h4.2M6.5 6.5l8-2.6 1.2 2.6" {...p} /></>;
      case "lock": return <><Rect x="5" y="10.5" width="14" height="9.5" rx="2.2" {...p} /><Path d="M8.3 10.5V8a3.7 3.7 0 0 1 7.4 0v2.5" {...p} /></>;
      case "logout": return <><Path d="M14 4.5H7.5a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2H14" {...p} /><Path d="M11 12h9M17 8.5l3.5 3.5-3.5 3.5" {...p} /></>;
      case "trash": return <><Path d="M5 7h14M9.5 7V5h5v2M7 7l.8 12.5h8.4L17 7" {...p} /></>;
      case "telegram": return <Path d="m20.5 4.5-17 6.6 5.5 1.9 1.8 5.6 3-3.4 4.3 3.3zM9 13l8.5-6.3-6.4 7.7" {...p} />;
      case "mail": return <><Rect x="3.5" y="5.5" width="17" height="13" rx="2.5" {...p} /><Path d="m4.5 7 7.5 6 7.5-6" {...p} /></>;
      case "refresh": return <><Path d="M19 12a7 7 0 1 1-2.1-5" {...p} /><Path d="M19.2 4.5v4h-4" {...p} /></>;
      case "chart": return <><Path d="M4 19.5h16" {...p} /><Path d="M7 15V9M11 17V6M15 14V8M19 12V5" {...p} /></>;
      case "bolt": return <Path d="M13 3.5 5.5 13.5H12l-1 7 7.5-10H12z" {...p} />;
      case "info": return <><Circle cx="12" cy="12" r="8.5" {...p} /><Path d="M12 11v5.5" {...p} /><Circle cx="12" cy="7.8" r=".9" fill={color} /></>;
      case "robot": return <><Rect x="5" y="8" width="14" height="11" rx="3" {...p} /><Path d="M12 4.5V8M9.5 13h.01M14.5 13h.01M9.5 16.2h5" {...p} /><Circle cx="12" cy="4" r="1" fill={color} /></>;
      case "edit": return <><Path d="M4.5 19.5h4l10-10-4-4-10 10z" {...p} /><Path d="m13 7 4 4" {...p} /></>;
      case "spark": return <Path d="M12 3.5c.7 4.4 2.6 6.6 7 7.5-4.4.9-6.3 3.1-7 7.5-.7-4.4-2.6-6.6-7-7.5 4.4-.9 6.3-3.1 7-7.5z" {...p} />;
    }
  })();
  return <Svg width={size} height={size} viewBox="0 0 24 24">{body}</Svg>;
}
