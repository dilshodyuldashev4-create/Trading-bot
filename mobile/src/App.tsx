import * as SplashScreen from "expo-splash-screen";
import { StatusBar } from "expo-status-bar";
import * as SystemUI from "expo-system-ui";
import React, { useEffect, useRef } from "react";
import { Animated, Easing, Platform, StyleSheet, View } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";

import Auth from "./screens/Auth";
import Home from "./screens/Home";
import { AnalysisScreen, CalendarScreen, ChartScreen, NewsScreen } from "./screens/Info";
import Learn, { LearnProvider, LessonScreen, VideoScreen } from "./screens/Learn";
import Profile from "./screens/Profile";
import Prop from "./screens/Prop";
import Stats from "./screens/Stats";
import { AppProvider, useApp, type Route } from "./store";
import { C } from "./theme";
import { Backdrop, OfflineBar, PromptSheet, TabBar, ToastView } from "./ui/layout";

SplashScreen.preventAutoHideAsync().catch(() => {});
SystemUI.setBackgroundColorAsync(C.bg).catch(() => {});

const native = Platform.OS !== "web";

function RouteView({ r }: { r: Route }) {
  switch (r.name) {
    case "analysis": return <AnalysisScreen />;
    case "news": return <NewsScreen />;
    case "calendar": return <CalendarScreen />;
    case "lesson": return <LessonScreen id={r.id} />;
    case "video": return <VideoScreen n={r.n} />;
    case "chart": return <ChartScreen id={r.id} />;
  }
}

/** Экран поверх вкладок: выезжает справа */
function Pushed({ r }: { r: Route }) {
  const a = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    Animated.timing(a, { toValue: 1, duration: 300, easing: Easing.out(Easing.cubic), useNativeDriver: native }).start();
  }, [a]);
  return (
    <Animated.View style={[StyleSheet.absoluteFill, {
      opacity: a, transform: [{ translateX: a.interpolate({ inputRange: [0, 1], outputRange: [60, 0] }) }],
    }]}>
      <Backdrop />
      <RouteView r={r} />
    </Animated.View>
  );
}

/** Смена вкладки — мягкое появление */
function TabContent() {
  const { tab, state } = useApp();
  const a = useRef(new Animated.Value(1)).current;
  useEffect(() => {
    a.setValue(0);
    Animated.timing(a, { toValue: 1, duration: 260, easing: Easing.out(Easing.quad), useNativeDriver: native }).start();
  }, [tab, a]);
  return (
    <Animated.View style={{ flex: 1, opacity: a }}>
      {tab === "home" || !state ? <Home /> : tab === "stats" ? <Stats /> : tab === "prop" ? <Prop /> : tab === "learn" ? <Learn /> : <Profile />}
    </Animated.View>
  );
}

function Root() {
  const { booting, authed, state, stack } = useApp();
  useEffect(() => {
    if (!booting) SplashScreen.hideAsync().catch(() => {});
  }, [booting]);
  if (booting) return <View style={{ flex: 1, backgroundColor: C.bg }} />;
  const top = stack[stack.length - 1];
  return (
    <View style={{ flex: 1 }}>
      <Backdrop />
      {!authed ? <Auth /> : (
        <>
          <TabContent />
          <TabBar />
          {top && state ? <Pushed key={stack.length + top.name} r={top} /> : null}
        </>
      )}
      <OfflineBar />
      <ToastView />
      <PromptSheet />
    </View>
  );
}

export default function App() {
  return (
    <SafeAreaProvider style={{ backgroundColor: C.bg }}>
      <StatusBar style="light" />
      <AppProvider>
        <LearnProvider>
          <Root />
        </LearnProvider>
      </AppProvider>
    </SafeAreaProvider>
  );
}
