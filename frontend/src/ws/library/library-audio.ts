const SOUND_PREF_KEY = "ynu_library_sound_enabled";

const audioPath = (filename: string) => `${import.meta.env.BASE_URL}audio/${filename}`;

const PAGE_SOUNDS = [
  audioPath("page-1.mp3"),
  audioPath("page-2.mp3"),
  audioPath("page-3.mp3"),
  audioPath("page-4.mp3"),
] as const;

const BGM_SOUND = audioPath("bgm.mp3");

type AudioTemplate = HTMLAudioElement | null;

class LibraryAudioController {
  private enabled = true;
  private armed = false;
  private bgm: HTMLAudioElement | null = null;
  private pageTemplates: HTMLAudioElement[] = [];
  private hiddenPaused = false;
  private lastPageSoundAt = 0;

  constructor() {
    if (typeof window !== "undefined") {
      try {
        const stored = window.localStorage.getItem(SOUND_PREF_KEY);
        this.enabled = stored === null ? true : stored === "1";
      } catch {
        this.enabled = true;
      }
    }
  }

  isEnabled() {
    return this.enabled;
  }

  arm() {
    if (typeof window === "undefined") return;

    if (!this.armed) {
      this.armed = true;
      this.prepareEffects();
    }

    if (this.enabled) {
      void this.startBgm();
    }
  }

  setEnabled(next: boolean) {
    this.enabled = next;

    if (typeof window !== "undefined") {
      try {
        window.localStorage.setItem(
          SOUND_PREF_KEY,
          next ? "1" : "0"
        );
      } catch {
        // 即使浏览器无法保存偏好，也继续按用户本次选择播放。
      }
    }

    if (next) {
      this.arm();
    } else {
      this.pauseBgm();
    }
  }

  toggle() {
    this.setEnabled(!this.enabled);
    return this.enabled;
  }

  playPage() {
    if (!this.enabled) return;
    this.arm();

    const now = performance.now();
    if (now - this.lastPageSoundAt < 120) return;
    this.lastPageSoundAt = now;

    if (!this.pageTemplates.length) return;

    const index = Math.floor(
      Math.random() * this.pageTemplates.length
    );

    this.playTemplate(
      this.pageTemplates[index],
      0.82
    );
  }

  handleVisibility(hidden: boolean) {
    if (hidden) {
      this.hiddenPaused = Boolean(
        this.bgm && !this.bgm.paused
      );
      this.pauseBgm();
      return;
    }

    if (
      this.hiddenPaused &&
      this.enabled &&
      this.armed
    ) {
      this.hiddenPaused = false;
      void this.startBgm();
    }
  }

  private prepareEffects() {
    if (typeof Audio === "undefined") return;

    if (!this.pageTemplates.length) {
      this.pageTemplates = PAGE_SOUNDS.map(src => {
        const audio = new Audio(src);
        audio.preload = "auto";
        audio.load();
        return audio;
      });
    }
  }

  private ensureBgm() {
    if (typeof Audio === "undefined") return null;

    if (!this.bgm) {
      const audio = new Audio(BGM_SOUND);
      audio.loop = true;
      audio.preload = "auto";
      audio.volume = 0.20;
      this.bgm = audio;
    }

    return this.bgm;
  }

  private async startBgm() {
    const bgm = this.ensureBgm();
    if (!bgm || !bgm.paused) return;

    try {
      await bgm.play();
    } catch {
      // 如果浏览器暂时没有开始播放，下一次用户操作时再试一次。
    }
  }

  private pauseBgm() {
    if (this.bgm && !this.bgm.paused) {
      this.bgm.pause();
    }
  }

  private playTemplate(
    template: AudioTemplate,
    volume: number
  ) {
    if (!template || typeof Audio === "undefined") {
      return;
    }

    const audio = template.cloneNode(true) as HTMLAudioElement;
    audio.volume = volume;
    audio.currentTime = 0;
    void audio.play().catch(() => {
      // 用户尚未完成浏览器要求的音频手势时静默失败。
    });
  }
}

export const libraryAudio = new LibraryAudioController();
