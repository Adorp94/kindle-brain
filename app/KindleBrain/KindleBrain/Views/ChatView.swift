import SwiftUI

struct ChatView: View {
    @EnvironmentObject var chatVM: ChatViewModel
    @FocusState private var isInputFocused: Bool

    var body: some View {
        VStack(spacing: 0) {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 24) {
                        if chatVM.messages.isEmpty {
                            emptyState
                        }

                        ForEach(chatVM.messages) { message in
                            MessageBubble(
                                message: message,
                                isThinking: chatVM.isLoading
                                    && message.id == chatVM.messages.last?.id
                                    && message.role == .assistant
                                    && message.text.isEmpty,
                                thinkingText: chatVM.thinkingText
                            )
                            .id(message.id)
                        }
                    }
                    .padding(.horizontal, 20)
                    .padding(.top, 12)
                    .padding(.bottom, 20)
                    .textSelection(.enabled)
                }
                .onChange(of: chatVM.messages.last?.text) { _, _ in
                    scrollToBottom(proxy)
                }
                .onChange(of: chatVM.isLoading) { _, _ in
                    scrollToBottom(proxy)
                }
                .onChange(of: chatVM.thinkingText) { _, _ in
                    scrollToBottom(proxy)
                }
            }

            Divider()

            inputBar
        }
        .navigationTitle("Chat")
    }

    // MARK: - Input Bar

    private var inputBar: some View {
        HStack(alignment: .bottom, spacing: 10) {
            TextField("Ask about your reading highlights...", text: $chatVM.inputText, axis: .vertical)
                .textFieldStyle(.plain)
                .lineLimit(1...6)
                .focused($isInputFocused)
                .onSubmit {
                    if !chatVM.inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                        Task { await chatVM.send() }
                    }
                }
                .padding(12)

            if chatVM.isLoading {
                Button(role: .destructive) {
                    chatVM.stop()
                } label: {
                    Image(systemName: "stop.circle.fill")
                        .font(.system(size: 30))
                }
                .buttonStyle(.plain)
                .help("Stop generating")
                .accessibilityLabel("Stop generating response")
            } else {
                Button {
                    Task { await chatVM.send() }
                } label: {
                    Image(systemName: "arrow.up.circle.fill")
                        .font(.system(size: 30))
                        .foregroundStyle(
                            chatVM.inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                                ? Color.gray.opacity(0.3)
                                : Color.accentColor
                        )
                }
                .buttonStyle(.plain)
                .disabled(chatVM.inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                .keyboardShortcut(.return, modifiers: .command)
                .accessibilityLabel("Send message")
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 14)
        .background(.ultraThinMaterial)
        .onKeyPress(.escape) {
            if chatVM.isLoading {
                chatVM.stop()
                return .handled
            }
            return .ignored
        }
    }

    private func scrollToBottom(_ proxy: ScrollViewProxy) {
        if let last = chatVM.messages.last {
            withAnimation(.easeOut(duration: 0.15)) {
                proxy.scrollTo(last.id, anchor: .bottom)
            }
        }
    }

    private var emptyState: some View {
        VStack(spacing: 24) {
            Spacer(minLength: 80)

            ZStack {
                Circle()
                    .fill(.thinMaterial)
                    .frame(width: 100, height: 100)
                Image(systemName: "brain.head.profile")
                    .font(.system(size: 44))
                    .foregroundStyle(Color.accentColor)
            }

            VStack(spacing: 8) {
                Text("Kindle Brain")
                    .font(.largeTitle.bold())
                Text("Ask questions about your reading highlights.\nI search through your golden nuggets and\nconnect ideas across all your books.")
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .lineSpacing(3)
            }

            Spacer(minLength: 80)
        }
        .frame(maxWidth: .infinity)
    }
}

// MARK: - Message Bubble

struct MessageBubble: View {
    let message: ChatMessage
    var isThinking: Bool = false
    var thinkingText: String = ""
    @State private var isSourcesExpanded = false
    @State private var showCopiedSources = false

    var body: some View {
        VStack(alignment: message.role == .user ? .trailing : .leading, spacing: 10) {
            // Role label
            HStack(spacing: 6) {
                Image(systemName: message.role == .user ? "person.circle.fill" : "brain.head.profile")
                    .font(.caption)
                Text(message.role == .user ? "You" : "Kindle Brain")
                    .font(.caption.bold())
            }
            .foregroundStyle(.secondary)
            .padding(.horizontal, 4)

            // Tool calls ABOVE response (like Claude's "Used kindle-clippings integration")
            if message.role == .assistant && !message.toolCalls.isEmpty {
                toolCallsSection
            }

            // Message content
            HStack(alignment: .top) {
                if message.role == .user { Spacer(minLength: 120) }

                if isThinking {
                    thinkingIndicator
                } else if message.role == .user {
                    Text(message.text)
                        .padding(14)
                        .background(.ultraThinMaterial)
                        .clipShape(RoundedRectangle(cornerRadius: 16))
                        .contextMenu {
                            Button {
                                NSPasteboard.general.clearContents()
                                NSPasteboard.general.setString(message.text, forType: .string)
                            } label: {
                                Label("Copy", systemImage: "doc.on.doc")
                            }
                        }
                } else {
                    MarkdownTextView(text: cleanResponse(message.text))
                        .padding(16)
                        .background(Color(nsColor: .controlBackgroundColor))
                        .clipShape(RoundedRectangle(cornerRadius: 16))
                        .contextMenu {
                            Button {
                                NSPasteboard.general.clearContents()
                                NSPasteboard.general.setString(message.text, forType: .string)
                            } label: {
                                Label("Copy Response", systemImage: "doc.on.doc")
                            }
                        }
                }

                if message.role == .assistant { Spacer(minLength: 60) }
            }

            // Sources (only show if no tool calls — avoid redundancy)
            if !message.sources.isEmpty && message.toolCalls.isEmpty {
                sourcesSection
            }
        }
        .frame(maxWidth: .infinity, alignment: message.role == .user ? .trailing : .leading)
    }

    /// Loading indicator while Pro reads books and synthesizes
    private var thinkingIndicator: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                ProgressView()
                    .scaleEffect(0.8)
                    .tint(Color.accentColor)

                Text("Reading your library...")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }

            // Show books being read in real-time
            if !message.toolCalls.isEmpty {
                let bookCalls = message.toolCalls.filter { $0.tool == "read_book" }
                if !bookCalls.isEmpty {
                    HStack(spacing: 6) {
                        Image(systemName: "book.closed.fill")
                            .font(.caption2)
                            .foregroundStyle(.orange)
                        Text(bookCalls.map { $0.args ?? "" }.joined(separator: ", "))
                            .font(.caption)
                            .foregroundStyle(.tertiary)
                            .lineLimit(2)
                    }
                }
            }
        }
        .padding(16)
        .frame(maxWidth: 400, alignment: .leading)
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 16))
    }

    @State private var isToolCallsExpanded = false

    private var toolCallsSection: some View {
        let bookCalls = message.toolCalls.filter { $0.tool == "read_book" }
        return VStack(alignment: .leading, spacing: 4) {
            DisclosureGroup(isExpanded: $isToolCallsExpanded) {
                VStack(alignment: .leading, spacing: 3) {
                    ForEach(bookCalls) { tc in
                        HStack(spacing: 6) {
                            Image(systemName: "book.closed.fill")
                                .font(.system(size: 9))
                                .foregroundStyle(.orange)
                            Text(tc.args ?? "")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .lineLimit(nil)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
                .padding(.leading, 4)
                .padding(.vertical, 4)
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "brain.head.profile")
                        .font(.caption)
                        .foregroundStyle(.orange)
                    Text("Read \(bookCalls.count) book\(bookCalls.count == 1 ? "" : "s") from your library")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var sourcesSection: some View {
        DisclosureGroup(isExpanded: $isSourcesExpanded) {
            VStack(alignment: .leading, spacing: 8) {
                ForEach(message.sources) { source in
                    HStack(alignment: .top, spacing: 10) {
                        Image(systemName: "book.closed.fill")
                            .foregroundStyle(.orange)
                            .font(.caption)
                            .frame(width: 16)
                        VStack(alignment: .leading, spacing: 3) {
                            Text(source.bookTitle)
                                .font(.caption.bold())
                            if let author = source.author, !author.isEmpty {
                                Text(author)
                                    .font(.caption2)
                                    .foregroundStyle(.tertiary)
                            }
                            if let page = source.page, page > 0 {
                                Text("p. \(page)")
                                    .font(.caption2)
                                    .foregroundStyle(.tertiary)
                            }
                            Text(source.highlight)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .lineLimit(nil)
                                .fixedSize(horizontal: false, vertical: true)
                                .italic()
                        }
                    }
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(.ultraThinMaterial)
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                    .contextMenu {
                        Button {
                            let text = formatSourceForCopy(source)
                            NSPasteboard.general.clearContents()
                            NSPasteboard.general.setString(text, forType: .string)
                        } label: {
                            Label("Copy Source", systemImage: "doc.on.doc")
                        }
                    }
                }

                // Copy all sources button
                Button {
                    let text = message.sources.map { formatSourceForCopy($0) }.joined(separator: "\n\n")
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(text, forType: .string)
                    showCopiedSources = true
                    DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
                        showCopiedSources = false
                    }
                } label: {
                    Label(showCopiedSources ? "Copied!" : "Copy All Sources",
                          systemImage: showCopiedSources ? "checkmark" : "doc.on.doc.fill")
                        .font(.caption)
                }
                .buttonStyle(.plain)
                .foregroundStyle(showCopiedSources ? .green : .orange)
                .animation(.easeInOut(duration: 0.2), value: showCopiedSources)
                .padding(.top, 4)
            }
            .padding(.top, 6)
        } label: {
            Label("\(message.sources.count) sources used", systemImage: "book.closed")
                .font(.caption)
                .foregroundStyle(.orange)
        }
        .padding(.leading, 4)
    }

    private func formatSourceForCopy(_ source: ChatSource) -> String {
        var parts = ["\(source.bookTitle)"]
        if let author = source.author, !author.isEmpty { parts.append("by \(author)") }
        if let page = source.page, page > 0 { parts.append("p. \(page)") }
        parts.append("\"\(source.highlight)\"")
        return parts.joined(separator: " — ")
    }

    private func cleanResponse(_ text: String) -> String {
        var cleaned = text
        cleaned = cleaned.replacingOccurrences(of: "«««", with: "")
        cleaned = cleaned.replacingOccurrences(of: "»»»", with: "")
        while cleaned.contains("  ") {
            cleaned = cleaned.replacingOccurrences(of: "  ", with: " ")
        }
        while cleaned.contains("\n\n\n") {
            cleaned = cleaned.replacingOccurrences(of: "\n\n\n", with: "\n\n")
        }
        return cleaned.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

// MARK: - Markdown Text View

/// Renders the entire response as a single AttributedString so text selection
/// works across the full message — user can select across paragraphs, quotes, etc.
struct MarkdownTextView: View {
    let text: String

    var body: some View {
        Text(buildAttributedString())
            .lineSpacing(5)
            .fixedSize(horizontal: false, vertical: true)
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

            if block.hasPrefix("### ") {
                var attr = parseInline(String(block.dropFirst(4)))
                attr.font = .headline
                result += attr
            } else if block.hasPrefix("## ") {
                var attr = parseInline(String(block.dropFirst(3)))
                attr.font = .title3.bold()
                result += attr
            } else if block.hasPrefix("# ") {
                var attr = parseInline(String(block.dropFirst(2)))
                attr.font = .title2.bold()
                result += attr
            } else if block.hasPrefix("> ") || block.hasPrefix(">") {
                let content = block
                    .components(separatedBy: "\n")
                    .map { line in
                        var l = line
                        if l.hasPrefix("> ") { l = String(l.dropFirst(2)) }
                        else if l.hasPrefix(">") { l = String(l.dropFirst(1)) }
                        return l
                    }
                    .joined(separator: "\n")
                var bar = AttributedString("▎ ")
                bar.foregroundColor = .orange
                result += bar
                var quote = parseInline(content)
                quote.foregroundColor = .secondary
                result += quote
            } else if block.hasPrefix("- ") || block.hasPrefix("* ") {
                let lines = block.components(separatedBy: "\n")
                for (i, line) in lines.enumerated() {
                    let trimmed = line.trimmingCharacters(in: .whitespaces)
                    if i > 0 { result += AttributedString("\n") }
                    if trimmed.hasPrefix("- ") || trimmed.hasPrefix("* ") {
                        let content = String(trimmed.dropFirst(2))
                        var bullet = AttributedString("  • ")
                        bullet.foregroundColor = .orange
                        result += bullet
                        result += parseInline(content)
                    } else if !trimmed.isEmpty {
                        result += parseInline(trimmed)
                    }
                }
            } else if block.first?.isNumber == true, block.contains(". ") {
                let lines = block.components(separatedBy: "\n")
                for (i, line) in lines.enumerated() {
                    let trimmed = line.trimmingCharacters(in: .whitespaces)
                    if i > 0 { result += AttributedString("\n") }
                    if let dotIdx = trimmed.firstIndex(of: "."),
                       let _ = Int(trimmed[trimmed.startIndex..<dotIdx]),
                       trimmed.index(after: dotIdx) < trimmed.endIndex {
                        let numStr = String(trimmed[trimmed.startIndex...dotIdx])
                        var numAttr = AttributedString(numStr + " ")
                        numAttr.foregroundColor = .orange
                        numAttr.font = .body.bold()
                        result += numAttr
                        let content = String(trimmed[trimmed.index(dotIdx, offsetBy: 2)...])
                        result += parseInline(content)
                    } else if !trimmed.isEmpty {
                        result += parseInline(trimmed)
                    }
                }
            } else if block.hasPrefix("***") || block.hasPrefix("---") {
                var divider = AttributedString("─────────────────")
                divider.foregroundColor = .gray.opacity(0.4)
                result += divider
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
