import Foundation

/// OpenAI-compatible REST client for xAI Grok API.
/// Handles tool-use loops with streaming simulation.
actor XAIService {
    static let shared = XAIService()

    private let baseURL = "https://api.x.ai/v1"

    var apiKey: String {
        UserDefaults.standard.string(forKey: "xaiAPIKey") ?? ""
    }

    var isConfigured: Bool { !apiKey.isEmpty }

    // MARK: - Types (matching GeminiService interface)

    struct ChatResult {
        let text: String
        let toolCalls: [ToolCallInfo]
    }

    typealias ToolExecutor = (String, [String: Any]) -> String

    enum StreamEvent {
        case toolCall(ToolCallInfo)
        case token(String)
        case done
    }

    // MARK: - Streaming Chat with Tool Use

    func chatStream(
        model: String,
        message: String,
        systemPrompt: String,
        tools: [ToolDef],
        executeToolCall: @escaping @Sendable ToolExecutor
    ) -> AsyncThrowingStream<StreamEvent, Error> {
        AsyncThrowingStream { continuation in
            Task {
                do {
                    var messages: [[String: Any]] = [
                        ["role": "system", "content": systemPrompt],
                        ["role": "user", "content": message]
                    ]

                    // Tool-use loop
                    for _ in 0..<10 {
                        let body = buildRequestBody(model: model, messages: messages, tools: tools)
                        let data = try await callAPI(endpoint: "/chat/completions", body: body)

                        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                              let choices = json["choices"] as? [[String: Any]],
                              let choice = choices.first,
                              let msg = choice["message"] as? [String: Any] else {
                            continuation.yield(.token("Failed to parse response."))
                            continuation.yield(.done)
                            continuation.finish()
                            return
                        }

                        // Check for tool calls
                        if let toolCalls = msg["tool_calls"] as? [[String: Any]], !toolCalls.isEmpty {
                            // Add assistant message with tool calls to history
                            messages.append(msg)

                            for tc in toolCalls {
                                guard let fn = tc["function"] as? [String: Any],
                                      let name = fn["name"] as? String,
                                      let argsJSON = fn["arguments"] as? String,
                                      let callId = tc["id"] as? String else { continue }

                                let args = (try? JSONSerialization.jsonObject(
                                    with: Data(argsJSON.utf8)
                                ) as? [String: Any]) ?? [:]

                                let result = executeToolCall(name, args)

                                let info = ToolCallInfo(
                                    tool: name,
                                    args: args["book_title"] as? String,
                                    summary: "Read \(name == "browse_library" ? "catalog" : args["book_title"] as? String ?? "book")"
                                )
                                continuation.yield(.toolCall(info))

                                // Add tool result
                                messages.append([
                                    "role": "tool",
                                    "tool_call_id": callId,
                                    "content": result
                                ])
                            }
                            continue
                        }

                        // No tool calls — final response
                        let text = msg["content"] as? String ?? ""
                        let chunkSize = 30
                        for i in stride(from: 0, to: text.count, by: chunkSize) {
                            let start = text.index(text.startIndex, offsetBy: i)
                            let end = text.index(start, offsetBy: min(chunkSize, text.distance(from: start, to: text.endIndex)))
                            continuation.yield(.token(String(text[start..<end])))
                            try await Task.sleep(nanoseconds: 10_000_000)
                        }
                        continuation.yield(.done)
                        continuation.finish()
                        return
                    }

                    continuation.yield(.done)
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
        }
    }

    // MARK: - Tool Definition (OpenAI format)

    struct ToolDef {
        let name: String
        let description: String
        let parameters: [String: Any] // JSON Schema properties
    }

    // MARK: - Private Helpers

    private func buildRequestBody(
        model: String,
        messages: [[String: Any]],
        tools: [ToolDef]
    ) -> [String: Any] {
        var body: [String: Any] = [
            "model": model,
            "messages": messages,
            "temperature": 1.0,
            "max_tokens": 8192,
            "stream": false
        ]

        if !tools.isEmpty {
            body["tools"] = tools.map { tool -> [String: Any] in
                var props: [String: Any] = [:]
                for (key, value) in tool.parameters {
                    props[key] = ["type": "string", "description": value]
                }
                return [
                    "type": "function",
                    "function": [
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": [
                            "type": "object",
                            "properties": props,
                            "required": Array(tool.parameters.keys)
                        ] as [String: Any]
                    ] as [String: Any]
                ]
            }
        }

        return body
    }

    private func callAPI(endpoint: String, body: [String: Any]) async throws -> Data {
        guard !apiKey.isEmpty else {
            throw XAIError.noAPIKey
        }

        let url = URL(string: "\(baseURL)\(endpoint)")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(apiKey)", forHTTPHeaderField: "Authorization")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        request.timeoutInterval = 120

        let (data, response) = try await URLSession.shared.data(for: request)

        if let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode != 200 {
            let errorText = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw XAIError.apiError(statusCode: httpResponse.statusCode, message: errorText)
        }

        return data
    }

    enum XAIError: LocalizedError {
        case noAPIKey
        case apiError(statusCode: Int, message: String)

        var errorDescription: String? {
            switch self {
            case .noAPIKey:
                return "No xAI API key configured. Go to Settings (Cmd+,) and enter your xAI API key."
            case .apiError(let code, let message):
                return "xAI API error (\(code)): \(message)"
            }
        }
    }
}
