(() => {
  const root = document.documentElement;
  const themeToggle = document.querySelector(".theme-toggle");
  const savedTheme = localStorage.getItem("youtube-playlist-theme");

  if (savedTheme === "light" || savedTheme === "dark") {
    root.dataset.theme = savedTheme;
  } else if (window.matchMedia("(prefers-color-scheme: light)").matches) {
    root.dataset.theme = "light";
  }

  const updateThemeButton = () => {
    const isDark = root.dataset.theme === "dark";
    themeToggle?.setAttribute("aria-label", `Switch to ${isDark ? "light" : "dark"} mode`);
    const icon = themeToggle?.querySelector(".theme-icon");
    if (icon) icon.textContent = isDark ? "☼" : "☾";
  };
  updateThemeButton();

  themeToggle?.addEventListener("click", () => {
    root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
    localStorage.setItem("youtube-playlist-theme", root.dataset.theme);
    updateThemeButton();
  });

  const analysisForm = document.querySelector("#analysis-form");

  const notice = document.querySelector("#form-notice");
  const resultsSection = document.querySelector("#analysis-results");
  const resultsList = document.querySelector("#results-list");
  const submitButton = analysisForm?.querySelector('button[type="submit"]');
  let scheduleVideos = null;
  let isSubmitting = false;
  let scheduleTimer = null;
  let scheduleRequestId = 0;

  const formatDuration = (seconds) => {
    if (seconds === null || seconds === undefined) return "Unavailable";
    if (seconds === 0) return "0 seconds";
    const units = [["day", 86400], ["hour", 3600], ["minute", 60], ["second", 1]];
    let remaining = seconds;
    return units.reduce((parts, [label, unit]) => {
      const count = Math.floor(remaining / unit);
      remaining %= unit;
      if (count) parts.push(`${count} ${label}${count === 1 ? "" : "s"}`);
      return parts;
    }, []).join(", ");
  };

  const element = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  const metric = (label, value) => {
    const wrapper = element("div", "result-metric");
    wrapper.append(element("span", "", label), element("strong", "", value));
    return wrapper;
  };

  const renderResult = (result) => {
    const card = element("article", "card result-card");
    const header = element("div", "result-header");
    const heading = element("div", "result-heading");
    if (result.error) {
      heading.append(element("h3", "", "Could not analyze this input"));
      heading.append(element("p", "result-input", result.input));
      header.append(heading);
      card.append(header, element("p", "result-error", result.error));
      return card;
    }

    heading.append(
      element("h3", "", result.title),
      element("p", "result-input", result.kind === "playlist" ? "Playlist" : "Video"),
    );
    if (result.creator) heading.append(element("p", "result-creator", result.creator));
    header.append(heading);
    if (result.videos?.[0]?.thumbnail_url) {
      const image = element("img", "result-thumbnail");
      image.src = result.videos[0].thumbnail_url;
      image.alt = `Thumbnail for ${result.title}`;
      image.loading = "lazy";
      header.append(image);
    }
    card.append(header);

    const summary = element("div", "result-metrics");
    summary.append(metric("Total duration", result.total_duration));
    summary.append(metric("Videos", `${result.accessible_video_count} of ${result.video_count} available`));
    if (result.range) summary.append(metric("Playlist range", `${result.range.start}–${result.range.end}`));
    card.append(summary);

    const playback = element("div", "result-playback");
    playback.append(element("h4", "", "Watch time by speed"));
    const speedList = element("div", "speed-results");
    result.playback_times.forEach((speed) => {
      speedList.append(metric(`${Number(speed.speed).toFixed(2)}x`, speed.duration));
    });
    playback.append(speedList);
    card.append(playback);

    const progress = element("div", "result-progress-row");
    const ring = element("div", "progress-ring result-progress");
    ring.style.setProperty("--progress", `${result.progress.percent}%`);
    ring.setAttribute("role", "img");
    ring.setAttribute("aria-label", `Watch progress: ${result.progress.percent} percent`);
    const ringText = element("div");
    ringText.append(
      element("strong", "", `${result.progress.percent}%`),
      element("span", "", `${result.progress.watched_count}/${result.progress.video_count}`),
    );
    ring.append(ringText);
    progress.append(ring);
    const progressValues = element("div", "result-progress-values");
    progressValues.append(
      metric("Watched", formatDuration(result.progress.watched_seconds)),
      metric("Remaining", formatDuration(result.progress.remaining_seconds)),
    );
    progress.append(progressValues);
    card.append(progress);

    if (result.limited_to_500_items) {
      card.append(element("p", "result-warning", "This playlist has more items; results are limited to the first 500."));
    }
    if (result.warning) card.append(element("p", "result-warning", result.warning));
    return card;
  };

  const updateSchedule = () => {
    if (!scheduleVideos) return;
    const requestId = ++scheduleRequestId;
    window.clearTimeout(scheduleTimer);
    const hours = Number(document.querySelector("#hours-per-day").value);
    const minutes = Number(document.querySelector("#minutes-per-day").value);
    const dailySeconds = Math.floor(hours * 3600 + minutes * 60);
    const weekdays = [...document.querySelectorAll("[data-watch-day]:checked")]
      .map((input) => Number(input.value));
    const speed = Number.parseFloat(document.querySelector("#schedule-speed").value);
    const includeToday = document.querySelector("#include-today").checked;
    const watched = scheduleVideos.progress;
    const remaining = watched.remaining_seconds;
    const scheduleMessage = document.querySelector("[data-schedule-message]");
    const finishElement = document.querySelector("[data-schedule-finish]");
    const scheduleRing = document.querySelector(".schedule-card .progress-ring");

    if (!Number.isInteger(hours) || hours < 0 || hours > 24 ||
        !Number.isInteger(minutes) || minutes < 0 || minutes > 59) {
      finishElement.textContent = "—";
      scheduleMessage.textContent = "Enter up to 24 hours and 59 minutes of daily watch time.";
      return;
    }

    document.querySelector("[data-schedule-watched]").textContent = formatDuration(watched.watched_seconds);
    document.querySelector("[data-schedule-remaining]").textContent = formatDuration(watched.remaining_seconds);
    document.querySelector("[data-schedule-total]").textContent = formatDuration(watched.total_seconds);
    scheduleRing.style.setProperty("--progress", `${watched.percent}%`);
    scheduleRing.setAttribute("aria-label", `Watch progress: ${watched.percent} percent`);

    if (watched.unavailable_remaining_count > 0 && watched.total_seconds === 0) {
      finishElement.textContent = "—";
      scheduleMessage.textContent = "Cannot estimate the schedule: remaining video durations are unavailable.";
      return;
    }
    if (remaining === 0 && watched.unavailable_remaining_count === 0) {
      finishElement.textContent = new Intl.DateTimeFormat(undefined, {dateStyle: "medium"}).format(new Date());
      scheduleMessage.textContent = `Schedule for ${scheduleVideos.title} is complete.`;
      return;
    }
    if (!dailySeconds || !weekdays.length) {
      finishElement.textContent = "—";
      scheduleMessage.textContent = "Choose at least one watching day and a daily watch time.";
      return;
    }

    finishElement.textContent = "Calculating…";
    scheduleMessage.textContent = watched.unavailable_remaining_count
      ? `Schedule for ${scheduleVideos.title} · ${Number(speed).toFixed(2)}x · excludes unavailable durations`
      : `Schedule for ${scheduleVideos.title} · ${Number(speed).toFixed(2)}x`;
    scheduleTimer = window.setTimeout(async () => {
      try {
        const response = await fetch("/api/schedule", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            remaining_seconds: remaining,
            daily_seconds: dailySeconds,
            watching_weekdays: weekdays,
            speed,
            include_today: includeToday,
            start_date: (() => {
              const today = new Date();
              const month = String(today.getMonth() + 1).padStart(2, "0");
              const day = String(today.getDate()).padStart(2, "0");
              return `${today.getFullYear()}-${month}-${day}`;
            })(),
          }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Could not calculate the schedule.");
        if (requestId !== scheduleRequestId) return;
        finishElement.textContent = data.finish_date
          ? new Intl.DateTimeFormat(undefined, {dateStyle: "medium"}).format(new Date(`${data.finish_date}T00:00:00`))
          : "—";
      } catch (error) {
        if (requestId !== scheduleRequestId) return;
        finishElement.textContent = "—";
        scheduleMessage.textContent = error instanceof TypeError
          ? "Could not reach the schedule service. Check your connection and try again."
          : error.message;
      }
    }, 100);
  };

  const renderResults = (results) => {
    resultsList.replaceChildren(...results.map(renderResult));
    resultsSection.hidden = false;
    const successful = results.filter((result) => !result.error);
    scheduleVideos = successful.find((result) => result.kind === "playlist") || successful[0] || null;
    if (scheduleVideos) {
      document.querySelector(".schedule-card").scrollIntoView({behavior: "smooth", block: "nearest"});
      updateSchedule();
    } else {
      scheduleRequestId += 1;
      window.clearTimeout(scheduleTimer);
      document.querySelector("[data-schedule-message]").textContent = "Analyze a playlist first to see your schedule.";
      document.querySelector("[data-schedule-finish]").textContent = "—";
      document.querySelector("[data-schedule-watched]").textContent = "—";
      document.querySelector("[data-schedule-remaining]").textContent = "—";
      document.querySelector("[data-schedule-total]").textContent = "—";
    }
  };

  analysisForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (isSubmitting) return;
    isSubmitting = true;
    notice.textContent = "Analyzing your YouTube links…";
    submitButton.disabled = true;
    submitButton.textContent = "Analyzing…";
    analysisForm.setAttribute("aria-busy", "true");

    const formData = new FormData(analysisForm);
    const body = {
      input_text: formData.get("input_text"),
      range_start: formData.get("range_start") || null,
      range_end: formData.get("range_end") || null,
      custom_speed: formData.get("custom_speed") || null,
      watched_count: formData.get("watched_count") || "0",
      api_key: formData.get("api_key") || null,
    };
    for (const field of ["range_start", "range_end", "custom_speed", "watched_count"]) {
      if (body[field] !== null) body[field] = Number(body[field]);
    }

    try {
      const response = await fetch("/api/analyze", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body),
      });
      const data = await response.json();
      if (!response.ok) {
        const detail = Array.isArray(data.detail)
          ? data.detail.map((issue) => issue.msg).join(" ")
          : data.detail;
        throw new Error(detail || "Analysis failed. Please try again.");
      }
      renderResults(data.results);
      const errors = data.results.filter((result) => result.error).length;
      notice.textContent = errors
        ? `Analysis finished with ${errors} input${errors === 1 ? "" : "s"} that could not be analyzed.`
        : "Analysis complete.";
    } catch (error) {
      notice.textContent = error instanceof TypeError
        ? "Could not reach the analysis service. Check your connection and try again."
        : error.message;
    } finally {
      isSubmitting = false;
      submitButton.disabled = false;
      submitButton.textContent = "Analyze Playlist";
      analysisForm.removeAttribute("aria-busy");
    }
  });

  document.querySelectorAll(
    "#hours-per-day, #minutes-per-day, #schedule-speed, #include-today, [data-watch-day]",
  ).forEach((control) => control.addEventListener("input", updateSchedule));
  document.querySelectorAll("#schedule-speed, #include-today, [data-watch-day]")
    .forEach((control) => control.addEventListener("change", updateSchedule));

  const postJson = async (path, body) => {
    const response = await fetch(path, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) {
      const detail = Array.isArray(data.detail)
        ? data.detail.map((issue) => issue.msg).join(" ")
        : data.detail;
      throw new Error(detail || "The request could not be completed.");
    }
    return data;
  };

  const thumbnailForm = document.querySelector("#thumbnail-form");
  if (thumbnailForm) {
    const thumbnailNotice = document.querySelector("#thumbnail-notice");
    const thumbnailResults = document.querySelector("#thumbnail-results");
    const thumbnailGrid = document.querySelector("#thumbnail-grid");
    const thumbnailSubmit = thumbnailForm.querySelector('button[type="submit"]');
    let loadingCount = 0;

    const createThumbnailCard = (videoId, variant) => {
      const card = element("article", "thumbnail-option");
      const image = element("img", "thumbnail-preview");
      image.src = variant.url;
      image.alt = `${variant.label} YouTube thumbnail`;
      image.loading = "lazy";
      const metadata = element("div", "thumbnail-meta");
      metadata.append(
        element("strong", "", variant.label),
        element("span", "", variant.resolution),
      );
      const status = element("span", "thumbnail-availability", "Checking image…");
      const actions = element("div", "thumbnail-actions");
      const openLink = element("a", "secondary-button", "Open full size");
      openLink.href = variant.url;
      openLink.target = "_blank";
      openLink.rel = "noopener noreferrer";
      const downloadButton = element("button", "small-button", "Download");
      downloadButton.type = "button";
      downloadButton.disabled = true;
      downloadButton.addEventListener("click", async () => {
        downloadButton.disabled = true;
        try {
          const response = await fetch(variant.url, {mode: "cors"});
          if (!response.ok) throw new Error("Image download failed.");
          const blob = await response.blob();
          const objectUrl = URL.createObjectURL(blob);
          const downloadLink = element("a");
          downloadLink.href = objectUrl;
          downloadLink.download = `youtube-thumbnail-${videoId}-${variant.key}.jpg`;
          document.body.append(downloadLink);
          downloadLink.click();
          downloadLink.remove();
          URL.revokeObjectURL(objectUrl);
          thumbnailNotice.textContent = `Downloading ${variant.label.toLowerCase()} thumbnail.`;
        } catch {
          thumbnailNotice.textContent = "Your browser blocked a direct download. Open the full-size image and use Save image as.";
          window.open(variant.url, "_blank", "noopener,noreferrer");
        } finally {
          downloadButton.disabled = false;
        }
      });

      image.addEventListener("load", () => {
        if (image.naturalWidth < 1 || image.naturalHeight < 1) {
          status.textContent = "Unavailable";
          status.classList.add("is-unavailable");
          return;
        }
        status.textContent = `${image.naturalWidth} × ${image.naturalHeight}`;
        downloadButton.disabled = false;
      });
      image.addEventListener("error", () => {
        status.textContent = "Unavailable";
        status.classList.add("is-unavailable");
        image.hidden = true;
        openLink.setAttribute("aria-disabled", "true");
        openLink.removeAttribute("href");
      });
      actions.append(openLink, downloadButton);
      card.append(image, metadata, status, actions);
      return card;
    };

    thumbnailForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (loadingCount) return;
      loadingCount += 1;
      thumbnailSubmit.disabled = true;
      thumbnailSubmit.textContent = "Checking…";
      thumbnailForm.setAttribute("aria-busy", "true");
      thumbnailNotice.textContent = "Checking available thumbnail images…";
      thumbnailGrid.replaceChildren();
      thumbnailResults.hidden = true;
      try {
        const data = await postJson("/api/thumbnail-variants", {
          video_input: new FormData(thumbnailForm).get("video_input"),
        });
        thumbnailGrid.replaceChildren(
          ...data.variants.map((variant) => createThumbnailCard(data.video_id, variant)),
        );
        thumbnailResults.hidden = false;
        thumbnailNotice.textContent = "Checking each thumbnail size. Unavailable sizes will be marked.";
      } catch (error) {
        thumbnailNotice.textContent = error instanceof TypeError
          ? "Could not reach the thumbnail service. Check your connection and try again."
          : error.message;
      } finally {
        loadingCount -= 1;
        thumbnailSubmit.disabled = false;
        thumbnailSubmit.textContent = "Get Thumbnails";
        thumbnailForm.removeAttribute("aria-busy");
      }
    });
  }

  const timestampForm = document.querySelector("#timestamp-form");
  if (timestampForm) {
    const timestampNotice = document.querySelector("#timestamp-notice");
    const timestampResult = document.querySelector("#timestamp-result");
    const timestampOutput = document.querySelector("#timestamp-output");
    const copyButton = document.querySelector("#copy-timestamp-link");
    const openLink = document.querySelector("#open-timestamp-link");
    const submit = timestampForm.querySelector('button[type="submit"]');
    let generatedUrl = "";
    let generating = false;

    timestampForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (generating) return;
      generating = true;
      submit.disabled = true;
      submit.textContent = "Generating…";
      timestampForm.setAttribute("aria-busy", "true");
      timestampNotice.textContent = "Generating your timestamp link…";
      try {
        const values = new FormData(timestampForm);
        const data = await postJson("/api/timestamp", {
          video_input: values.get("video_input"),
          timestamp: values.get("timestamp"),
        });
        generatedUrl = data.url;
        timestampOutput.textContent = generatedUrl;
        openLink.href = generatedUrl;
        timestampResult.hidden = false;
        timestampNotice.textContent = `Timestamp link ready (${formatDuration(data.seconds)}).`;
      } catch (error) {
        timestampResult.hidden = true;
        timestampNotice.textContent = error instanceof TypeError
          ? "Could not reach the timestamp service. Check your connection and try again."
          : error.message;
      } finally {
        generating = false;
        submit.disabled = false;
        submit.textContent = "Generate Link";
        timestampForm.removeAttribute("aria-busy");
      }
    });

    copyButton.addEventListener("click", async () => {
      if (!generatedUrl) return;
      try {
        if (navigator.clipboard?.writeText) {
          await navigator.clipboard.writeText(generatedUrl);
        } else {
          const temporary = element("textarea");
          temporary.value = generatedUrl;
          temporary.setAttribute("readonly", "");
          temporary.style.position = "fixed";
          temporary.style.opacity = "0";
          document.body.append(temporary);
          temporary.select();
          const copied = document.execCommand("copy");
          temporary.remove();
          if (!copied) throw new Error("Clipboard access is unavailable.");
        }
        timestampNotice.textContent = "Timestamp link copied to clipboard.";
      } catch {
        timestampNotice.textContent = "Could not copy automatically. Select and copy the link above.";
      }
    });
  }
})();
