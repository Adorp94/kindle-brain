import SwiftUI

// MARK: - Cover Image Cache

/// Loads cover images from disk once and caches in memory.
/// Avoids repeated file I/O on every SwiftUI body evaluation.
final class CoverImageCache {
    static let shared = CoverImageCache()
    private var cache: [Int: NSImage] = [:]

    func image(for book: Book) -> NSImage? {
        if let cached = cache[book.id] { return cached }
        guard let url = book.coverURL,
              let img = NSImage(contentsOf: url) else { return nil }
        cache[book.id] = img
        return img
    }
}

struct LibraryDetailView: View {
    @EnvironmentObject var libraryVM: LibraryViewModel

    var body: some View {
        Group {
            if let book = libraryVM.selectedBook {
                bookDetail(book)
            } else {
                bookGrid
            }
        }
        .navigationTitle(libraryVM.selectedBook?.title ?? "Library")
    }

    // MARK: - Book Grid (no book selected)

    private var bookGrid: some View {
        ScrollView {
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 160, maximum: 200), spacing: 20)], spacing: 24) {
                ForEach(libraryVM.filteredBooks) { book in
                    BookGridItem(book: book) {
                        libraryVM.selectBook(book)
                    }
                }
            }
            .padding(24)
        }
    }

    // MARK: - Book Detail

    @ViewBuilder
    private func bookDetail(_ book: Book) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                // Back button
                Button {
                    libraryVM.selectedBook = nil
                    libraryVM.highlights = []
                    libraryVM.bookInfo = nil
                    libraryVM.highlightSearch = ""
                } label: {
                    HStack(spacing: 4) {
                        Image(systemName: "chevron.left")
                        Text("All Books")
                    }
                    .font(.callout)
                }
                .buttonStyle(.plain)
                .foregroundStyle(Color.accentColor)

                // Book header card
                HStack(alignment: .top, spacing: 20) {
                    // Cover
                    if let nsImage = CoverImageCache.shared.image(for: book) {
                        Image(nsImage: nsImage)
                            .resizable()
                            .aspectRatio(contentMode: .fit)
                            .frame(width: 120)
                            .clipShape(RoundedRectangle(cornerRadius: 8))
                            .shadow(color: .black.opacity(0.15), radius: 8, y: 4)
                    }

                    VStack(alignment: .leading, spacing: 12) {
                        Text(book.title)
                            .font(.title.bold())
                        if let author = book.author {
                            Text(author)
                                .font(.title3)
                                .foregroundStyle(.secondary)
                        }

                        HStack(spacing: 20) {
                            StatBadge(icon: "text.quote", label: "Highlights", value: "\(book.highlightCount)")
                            if let first = book.firstHighlight, let last = book.lastHighlight {
                                StatBadge(icon: "calendar", label: "Period", value: "\(first) — \(last)")
                            }
                        }
                    }
                }
                .padding(20)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(.ultraThinMaterial)
                .clipShape(RoundedRectangle(cornerRadius: 16))

                if let summary = libraryVM.bookInfo?.summary, !summary.isEmpty {
                    VStack(alignment: .leading, spacing: 8) {
                        Label("Summary", systemImage: "doc.text")
                            .font(.headline)
                        SummaryTextView(text: summary)
                    }
                    .padding(16)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(.ultraThinMaterial)
                    .clipShape(RoundedRectangle(cornerRadius: 12))
                }

                Divider()

                // Highlights header with search
                HStack {
                    Text("\(libraryVM.filteredHighlights.count) Highlights")
                        .font(.headline)
                        .foregroundStyle(.secondary)

                    Spacer()

                    HStack(spacing: 6) {
                        Image(systemName: "magnifyingglass")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        TextField("Search highlights...", text: $libraryVM.highlightSearch)
                            .textFieldStyle(.plain)
                            .frame(width: 180)
                        if !libraryVM.highlightSearch.isEmpty {
                            Button {
                                libraryVM.highlightSearch = ""
                            } label: {
                                Image(systemName: "xmark.circle.fill")
                                    .font(.caption)
                                    .foregroundStyle(.tertiary)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(6)
                    .background(.ultraThinMaterial)
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                }

                if libraryVM.isLoading && libraryVM.highlights.isEmpty {
                    HStack {
                        Spacer()
                        ProgressView("Loading highlights...")
                        Spacer()
                    }
                    .padding(.vertical, 40)
                } else {
                    LazyVStack(alignment: .leading, spacing: 16) {
                        ForEach(libraryVM.filteredHighlights) { highlight in
                            HighlightCard(highlight: highlight)
                        }
                    }

                    if libraryVM.filteredHighlights.isEmpty && !libraryVM.highlightSearch.isEmpty {
                        VStack(spacing: 8) {
                            Image(systemName: "magnifyingglass")
                                .font(.title2)
                                .foregroundStyle(.tertiary)
                            Text("No highlights match \"\(libraryVM.highlightSearch)\"")
                                .font(.callout)
                                .foregroundStyle(.secondary)
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 40)
                    }
                }
            }
            .padding(24)
            .textSelection(.enabled)
        }
    }
}

// MARK: - Book Grid Item

struct BookGridItem: View {
    let book: Book
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 10) {
                // Cover or placeholder
                if let nsImage = CoverImageCache.shared.image(for: book) {
                    Image(nsImage: nsImage)
                        .resizable()
                        .aspectRatio(2/3, contentMode: .fill)
                        .frame(height: 220)
                        .clipped()
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                } else {
                    coverPlaceholder
                }

                VStack(spacing: 3) {
                    Text(book.title)
                        .font(.caption.bold())
                        .lineLimit(2)
                        .multilineTextAlignment(.center)
                        .foregroundStyle(.primary)

                    if let author = book.author {
                        Text(author)
                            .font(.caption2)
                            .lineLimit(1)
                            .foregroundStyle(.secondary)
                    }

                    Text("\(book.highlightCount) highlights")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
            }
            .frame(maxWidth: .infinity)
        }
        .buttonStyle(.plain)
        .contextMenu {
            Button { action() } label: {
                Label("View Book", systemImage: "book")
            }
            Button {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(book.title, forType: .string)
            } label: {
                Label("Copy Title", systemImage: "doc.on.doc")
            }
        }
    }

    private var coverPlaceholder: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 8)
                .fill(.regularMaterial)

            VStack(spacing: 8) {
                Image(systemName: "book.closed.fill")
                    .font(.system(size: 28))
                    .foregroundStyle(.secondary)
                Text(book.title)
                    .font(.system(size: 10, weight: .medium))
                    .multilineTextAlignment(.center)
                    .lineLimit(3)
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 12)
            }
        }
        .frame(height: 220)
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .stroke(Color(nsColor: .separatorColor), lineWidth: 0.5)
        )
    }
}

// MARK: - Supporting Views

struct StatBadge: View {
    let icon: String
    let label: String
    let value: String

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: icon)
                .font(.caption)
                .foregroundStyle(.orange)
            VStack(alignment: .leading, spacing: 1) {
                Text(value)
                    .font(.callout.bold())
                Text(label)
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
        }
    }
}

struct HighlightCard: View {
    let highlight: Highlight
    @State private var explanation: String?
    @State private var isExplaining = false
    @State private var showExplanation = false
    @State private var showCopied = false

    private var data: DataService { DataService.shared }
    private var gemini: GeminiService { GeminiService.shared }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let chapter = highlight.chapter {
                Text(chapter)
                    .font(.caption.bold())
                    .foregroundStyle(.white)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 3)
                    .background(Color.accentColor)
                    .clipShape(Capsule())
            }

            HStack(alignment: .top, spacing: 12) {
                Rectangle()
                    .fill(Color.accentColor)
                    .frame(width: 3)

                Text(highlight.text)
                    .font(.body)
                    .lineSpacing(3)
            }

            HStack(spacing: 14) {
                if let page = highlight.page {
                    Label("p. \(page)", systemImage: "book")
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                }
                if let date = highlight.date {
                    Label(date, systemImage: "calendar")
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                }
                Spacer()

                // Explain button
                Button {
                    if explanation != nil {
                        showExplanation.toggle()
                    } else {
                        fetchExplanation()
                    }
                } label: {
                    if isExplaining {
                        ProgressView()
                            .scaleEffect(0.5)
                            .frame(width: 14, height: 14)
                    } else {
                        Image(systemName: showExplanation ? "lightbulb.fill" : "lightbulb")
                            .font(.caption)
                            .foregroundStyle(showExplanation ? .orange : .secondary)
                    }
                }
                .buttonStyle(.plain)
                .help("Explain this highlight")
                .accessibilityLabel(showExplanation ? "Hide explanation" : "Explain this highlight")

                Button {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(highlight.text, forType: .string)
                    showCopied = true
                    DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
                        showCopied = false
                    }
                } label: {
                    HStack(spacing: 3) {
                        Image(systemName: showCopied ? "checkmark" : "doc.on.doc")
                            .font(.caption)
                            .foregroundStyle(showCopied ? .green : .secondary)
                        if showCopied {
                            Text("Copied")
                                .font(.caption2)
                                .foregroundStyle(.green)
                                .transition(.opacity)
                        }
                    }
                    .animation(.easeInOut(duration: 0.2), value: showCopied)
                }
                .buttonStyle(.plain)
                .help("Copy highlight")
                .accessibilityLabel("Copy highlight text")
            }

            // Explanation block
            if showExplanation, let explanation {
                HStack(alignment: .top, spacing: 8) {
                    Image(systemName: "lightbulb.fill")
                        .font(.caption)
                        .foregroundStyle(.orange)
                    Text(parseMarkdownInline(explanation))
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .lineSpacing(2)
                }
                .padding(10)
                .background(.ultraThinMaterial)
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .transition(.opacity.combined(with: .move(edge: .top)))
            }

            if let note = highlight.note, !note.isEmpty {
                HStack(alignment: .top, spacing: 8) {
                    Image(systemName: "note.text")
                        .font(.caption)
                        .foregroundStyle(.orange)
                    Text(note)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .italic()
                }
                .padding(10)
                .background(.ultraThinMaterial)
                .clipShape(RoundedRectangle(cornerRadius: 8))
            }
        }
        .padding(16)
        .background(Color(nsColor: .controlBackgroundColor))
        .clipShape(RoundedRectangle(cornerRadius: 14))
        .overlay(
            RoundedRectangle(cornerRadius: 14)
                .stroke(Color(nsColor: .separatorColor), lineWidth: 0.5)
        )
        .contextMenu {
            Button {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(highlight.text, forType: .string)
            } label: {
                Label("Copy Highlight", systemImage: "doc.on.doc")
            }
            Button {
                if explanation != nil { showExplanation.toggle() }
                else { fetchExplanation() }
            } label: {
                Label("Explain", systemImage: "lightbulb")
            }
        }
        .animation(.easeInOut(duration: 0.2), value: showExplanation)
    }

    private func parseMarkdownInline(_ text: String) -> AttributedString {
        if let md = try? AttributedString(markdown: text, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)) {
            return md
        }
        return AttributedString(text)
    }

    private func fetchExplanation() {
        isExplaining = true
        Task {
            do {
                guard let ctx = await data.getHighlightContext(id: highlight.id) else {
                    throw NSError(domain: "", code: 0, userInfo: [NSLocalizedDescriptionKey: "Highlight not found"])
                }

                // Build prompt with context
                var parts: [String] = ["Book: \(ctx.bookTitle) by \(ctx.author ?? "")"]
                if let ch = ctx.chapterTitle { parts.append("Chapter: \(ch)") }
                if let cs = ctx.chapterSummary { parts.append("Chapter summary: \(cs)") }

                if let rc = ctx.richContext {
                    var clean = rc.replacingOccurrences(of: "«««", with: "[HIGHLIGHTED: ")
                                  .replacingOccurrences(of: "»»»", with: "]")
                    if clean.count > 8000 {
                        let markerPos = clean.range(of: "[HIGHLIGHTED:")?.lowerBound ?? clean.startIndex
                        let start = clean.index(markerPos, offsetBy: -3000, limitedBy: clean.startIndex) ?? clean.startIndex
                        let end = clean.index(markerPos, offsetBy: 5000, limitedBy: clean.endIndex) ?? clean.endIndex
                        clean = String(clean[start..<end])
                    }
                    parts.append("Surrounding text:\n\(clean)")
                } else if let sc = ctx.surroundingContext {
                    parts.append("Context: \(sc)")
                }

                let prompt = """
                    The reader highlighted this passage and wants to understand why it matters.

                    \(parts.joined(separator: "\n\n"))

                    HIGHLIGHTED PASSAGE: "\(ctx.text)"

                    Explain briefly (2-3 sentences) what the author was discussing.
                    Focus on the argument being built and why this passage matters.
                    Write in the same language as the highlighted text.
                    """

                let result = try await gemini.generateContent(prompt: prompt)
                await MainActor.run {
                    explanation = result
                    showExplanation = true
                    isExplaining = false
                }
            } catch {
                await MainActor.run {
                    explanation = "Could not generate explanation: \(error.localizedDescription)"
                    showExplanation = true
                    isExplaining = false
                }
            }
        }
    }
}

// MARK: - Summary Markdown Renderer

struct SummaryTextView: View {
    let text: String

    var body: some View {
        Text(buildAttributedString())
            .font(.body)
            .foregroundStyle(.secondary)
            .lineSpacing(4)
    }

    private func buildAttributedString() -> AttributedString {
        let paragraphs = text.components(separatedBy: "\n\n")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }

        var result = AttributedString()

        for (index, block) in paragraphs.enumerated() {
            if index > 0 {
                result += AttributedString("\n\n")
            }

            if block.hasPrefix("- ") || block.hasPrefix("* ") {
                let lines = block.components(separatedBy: "\n")
                for (i, line) in lines.enumerated() {
                    let trimmed = line.trimmingCharacters(in: .whitespaces)
                    if i > 0 { result += AttributedString("\n") }
                    if trimmed.hasPrefix("- ") || trimmed.hasPrefix("* ") {
                        let content = String(trimmed.dropFirst(2))
                        var bullet = AttributedString("  \u{2022} ")
                        bullet.foregroundColor = .orange
                        result += bullet
                        result += parseInline(content)
                    } else if !trimmed.isEmpty {
                        result += parseInline(trimmed)
                    }
                }
            } else if block.hasPrefix("### ") {
                var attr = parseInline(String(block.dropFirst(4)))
                attr.font = .headline
                attr.foregroundColor = nil
                result += attr
            } else if block.hasPrefix("## ") {
                var attr = parseInline(String(block.dropFirst(3)))
                attr.font = .title3.bold()
                attr.foregroundColor = nil
                result += attr
            } else {
                result += parseInline(block)
            }
        }

        return result
    }

    private func parseInline(_ text: String) -> AttributedString {
        if let md = try? AttributedString(markdown: text, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)) {
            return md
        }
        return AttributedString(text)
    }
}
