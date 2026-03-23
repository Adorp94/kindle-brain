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
                .background(Color.primary.opacity(0.04))
                .clipShape(RoundedRectangle(cornerRadius: 14))

            if chatVM.isLoading {
                Button {
                    chatVM.stop()
                } label: {
                    Image(systemName: "stop.circle.fill")
                        .font(.system(size: 30))
                        .foregroundStyle(Color.red.opacity(0.8))
                }
                .buttonStyle(.plain)
                .help("Stop generating")
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
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 14)
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
                    .fill(Color.accentColor.opacity(0.1))
                    .frame(width: 100, height: 100)
                Image(systemName: "brain.head.profile")
                    .font(.system(size: 44))
                    .foregroundStyle(Color.accentColor.opacity(0.7))
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

            // Message content
            HStack(alignment: .top) {
                if message.role == .user { Spacer(minLength: 120) }

                if isThinking {
                    thinkingIndicator
                } else if message.role == .user {
                    Text(message.text)
                        .textSelection(.enabled)
                        .padding(14)
                        .background(Color.accentColor.opacity(0.1))
                        .clipShape(RoundedRectangle(cornerRadius: 16))
                } else {
                    MarkdownTextView(text: cleanResponse(message.text))
                        .textSelection(.enabled)
                        .padding(16)
                        .background(Color.secondary.opacity(0.05))
                        .clipShape(RoundedRectangle(cornerRadius: 16))
                }

                if message.role == .assistant { Spacer(minLength: 60) }
            }

            // Sources
            if !message.sources.isEmpty {
                sourcesSection
            }
        }
        .frame(maxWidth: .infinity, alignment: message.role == .user ? .trailing : .leading)
    }

    /// Single thinking/loading indicator with reasoning status
    private var thinkingIndicator: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                ProgressView()
                    .scaleEffect(0.8)
                    .tint(Color.accentColor)

                if thinkingText.isEmpty {
                    Text("Searching through your highlights...")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                } else {
                    Text("Reasoning...")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
            }

            if !thinkingText.isEmpty {
                // Show a preview of the model's thinking
                let preview = String(thinkingText.suffix(200))
                Text(preview)
                    .font(.caption)
                    .foregroundStyle(.tertiary)
                    .lineLimit(3)
                    .italic()
            }
        }
        .padding(16)
        .frame(maxWidth: 400, alignment: .leading)
        .background(Color.secondary.opacity(0.05))
        .clipShape(RoundedRectangle(cornerRadius: 16))
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
                                .textSelection(.enabled)
                            if !source.author.isEmpty {
                                Text(source.author)
                                    .font(.caption2)
                                    .foregroundStyle(.tertiary)
                                    .textSelection(.enabled)
                            }
                            if let page = source.page, page > 0 {
                                Text("p. \(page)")
                                    .font(.caption2)
                                    .foregroundStyle(.tertiary)
                            }
                            Text(source.highlight)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .lineLimit(3)
                                .italic()
                                .textSelection(.enabled)
                        }
                    }
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.orange.opacity(0.04))
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
                } label: {
                    Label("Copy All Sources", systemImage: "doc.on.doc.fill")
                        .font(.caption)
                }
                .buttonStyle(.plain)
                .foregroundStyle(.orange)
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
        if !source.author.isEmpty { parts.append("by \(source.author)") }
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
/// works across the full message — not limited to individual paragraphs.
struct MarkdownTextView: View {
    let text: String

    var body: some View {
        Text(buildAttributedString())
            .lineSpacing(5)
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
                var attr = AttributedString(String(block.dropFirst(4)))
                attr.font = .headline
                result += attr
            } else if block.hasPrefix("## ") {
                var attr = AttributedString(String(block.dropFirst(3)))
                attr.font = .title3.bold()
                result += attr
            } else if block.hasPrefix("# ") {
                var attr = AttributedString(String(block.dropFirst(2)))
                attr.font = .title2.bold()
                result += attr
            } else if block.hasPrefix("> ") {
                // Blockquote: vertical bar character + italic text
                let quoteContent = block.dropFirst(2)
                    .replacingOccurrences(of: "\n> ", with: "\n")
                    .replacingOccurrences(of: "\n>", with: "\n")
                var bar = AttributedString("▎ ")
                bar.foregroundColor = .orange
                result += bar
                if let md = try? AttributedString(markdown: quoteContent, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)) {
                    var styled = md
                    styled.foregroundColor = .secondary
                    result += styled
                } else {
                    var styled = AttributedString(String(quoteContent))
                    styled.foregroundColor = .secondary
                    result += styled
                }
            } else if block.hasPrefix("- ") || block.hasPrefix("* ") {
                // Bullet list
                let lines = block.components(separatedBy: "\n")
                for (i, line) in lines.enumerated() {
                    let trimmed = line.trimmingCharacters(in: .whitespaces)
                    if i > 0 { result += AttributedString("\n") }
                    if trimmed.hasPrefix("- ") || trimmed.hasPrefix("* ") {
                        let content = String(trimmed.dropFirst(2))
                        var bullet = AttributedString("  \u{2022} ")
                        bullet.foregroundColor = .secondary
                        result += bullet
                        if let md = try? AttributedString(markdown: content, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)) {
                            result += md
                        } else {
                            result += AttributedString(content)
                        }
                    } else if !trimmed.isEmpty {
                        result += parseInlineMarkdown(trimmed)
                    }
                }
            } else if block.hasPrefix("***") || block.hasPrefix("---") {
                var divider = AttributedString("─────────────────")
                divider.foregroundColor = Color.gray.opacity(0.4)
                result += divider
            } else {
                // Regular paragraph — parse inline markdown (bold, italic, links)
                result += parseInlineMarkdown(block)
            }
        }

        return result
    }

    /// Parse inline markdown (bold, italic, code, links) into an AttributedString
    private func parseInlineMarkdown(_ text: String) -> AttributedString {
        if let md = try? AttributedString(markdown: text, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)) {
            return md
        }
        return AttributedString(text)
    }
}
