import Foundation

/// LLM-agnostic REST client for Gemini API.
/// Handles tool-use loops and streaming via URLSession.
/// No SDK dependency — pure REST calls.
actor GeminiService {
    static let shared = GeminiService()

    private let baseURL = "https://generativelanguage.googleapis.com/v1beta"
    private let chatModel = "gemini-3.1-pro-preview"
    private let flashModel = "gemini-3.1-flash-lite-preview"

    var apiKey: String {
        UserDefaults.standard.string(forKey: "geminiAPIKey") ?? ""
    }

    var isConfigured: Bool { !apiKey.isEmpty }

    // MARK: - Simple Generation (for explain highlight)

    func generateContent(prompt: String, temperature: Double = 0.3, maxTokens: Int = 300) async throws -> String {
        let body: [String: Any] = [
            "contents": [["role": "user", "parts": [["text": prompt]]]],
            "generationConfig": ["temperature": temperature, "maxOutputTokens": maxTokens]
        ]

        let data = try await callAPI(model: flashModel, action: "generateContent", body: body)
        return extractText(from: data) ?? "No response generated."
    }

    // MARK: - Chat with Tool Use (non-streaming)

    struct ToolDefinition {
        let name: String
        let description: String
        let parameters: [String: Any]
    }

    struct ChatResult {
        let text: String
        let toolCalls: [ToolCallInfo]
    }

    typealias ToolExecutor = (String, [String: Any]) -> String

    func chat(
        message: String,
        systemPrompt: String,
        tools: [ToolDefinition],
        executeToolCall: ToolExecutor
    ) async throws -> ChatResult {
        var contents: [[String: Any]] = [
            ["role": "user", "parts": [["text": message]]]
        ]
        var allToolCalls: [ToolCallInfo] = []

        // Tool-use loop: keep calling until we get text (no more function calls)
        for _ in 0..<10 { // Safety limit
            let body = buildRequestBody(
                contents: contents,
                systemPrompt: systemPrompt,
                tools: tools,
                temperature: 1.0,
                maxTokens: 8192
            )

            let data = try await callAPI(model: chatModel, action: "generateContent", body: body)

            // Check if response has function calls
            let (functionCalls, rawModelParts) = extractFunctionCallsAndModelParts(from: data)

            if functionCalls.isEmpty {
                // No more tool calls — we have the final response
                let text = extractText(from: data) ?? ""
                return ChatResult(text: text, toolCalls: allToolCalls)
            }

            // Execute each function call and build responses
            var functionResponseParts: [[String: Any]] = []

            for fc in functionCalls {
                let result = executeToolCall(fc.name, fc.args)
                allToolCalls.append(ToolCallInfo(
                    tool: fc.name,
                    args: fc.args["book_title"] as? String ?? (fc.args.isEmpty ? nil : String(describing: fc.args)),
                    summary: "Read \(fc.name == "browse_library" ? "catalog" : fc.args["book_title"] as? String ?? "book")"
                ))

                functionResponseParts.append([
                    "functionResponse": [
                        "name": fc.name,
                        "response": ["result": result]
                    ]
                ])
            }

            // Replay raw model parts (preserves thoughtSignature) + our responses
            contents.append(["role": "model", "parts": rawModelParts])
            contents.append(["role": "function", "parts": functionResponseParts])
        }

        return ChatResult(text: "Tool loop limit reached.", toolCalls: allToolCalls)
    }

    // MARK: - Streaming Chat with Tool Use

    enum StreamEvent {
        case toolCall(ToolCallInfo)
        case token(String)
        case done
    }

    func chatStream(
        message: String,
        systemPrompt: String,
        tools: [ToolDefinition],
        executeToolCall: @escaping @Sendable ToolExecutor
    ) -> AsyncThrowingStream<StreamEvent, Error> {
        AsyncThrowingStream { continuation in
            Task {
                do {
                    // Phase 1: Non-streaming tool-use loop
                    var contents: [[String: Any]] = [
                        ["role": "user", "parts": [["text": message]]]
                    ]

                    // Tool loop
                    for _ in 0..<10 {
                        let body = buildRequestBody(
                            contents: contents,
                            systemPrompt: systemPrompt,
                            tools: tools,
                            temperature: 1.0,
                            maxTokens: 8192
                        )

                        let data = try await callAPI(model: chatModel, action: "generateContent", body: body)
                        let (functionCalls, rawModelParts) = extractFunctionCallsAndModelParts(from: data)

                        if functionCalls.isEmpty {
                            // Final response — stream it token-like
                            let text = extractText(from: data) ?? ""
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

                        // Execute tools
                        var functionResponseParts: [[String: Any]] = []

                        for fc in functionCalls {
                            let result = executeToolCall(fc.name, fc.args)
                            let info = ToolCallInfo(
                                tool: fc.name,
                                args: fc.args["book_title"] as? String,
                                summary: "Read \(fc.name == "browse_library" ? "catalog" : fc.args["book_title"] as? String ?? "book")"
                            )
                            continuation.yield(.toolCall(info))

                            functionResponseParts.append([
                                "functionResponse": [
                                    "name": fc.name,
                                    "response": ["result": result]
                                ]
                            ])
                        }

                        contents.append(["role": "model", "parts": rawModelParts])
                        contents.append(["role": "function", "parts": functionResponseParts])
                    }

                    continuation.yield(.done)
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
        }
    }

    // MARK: - Private Helpers

    private struct FunctionCall {
        let name: String
        let args: [String: Any]
        let rawPart: [String: Any]  // Original part dict including thoughtSignature
    }

    private func buildRequestBody(
        contents: [[String: Any]],
        systemPrompt: String,
        tools: [ToolDefinition],
        temperature: Double,
        maxTokens: Int
    ) -> [String: Any] {
        var body: [String: Any] = [
            "contents": contents,
            "generationConfig": [
                "temperature": temperature,
                "maxOutputTokens": maxTokens
            ]
        ]

        if !systemPrompt.isEmpty {
            body["systemInstruction"] = ["parts": [["text": systemPrompt]]]
        }

        if !tools.isEmpty {
            let declarations = tools.map { tool -> [String: Any] in
                var decl: [String: Any] = [
                    "name": tool.name,
                    "description": tool.description
                ]
                if !tool.parameters.isEmpty {
                    decl["parameters"] = [
                        "type": "OBJECT",
                        "properties": tool.parameters
                    ]
                }
                return decl
            }
            body["tools"] = [["functionDeclarations": declarations]]
        }

        return body
    }

    private func callAPI(model: String, action: String, body: [String: Any]) async throws -> Data {
        guard !apiKey.isEmpty else {
            throw GeminiError.noAPIKey
        }

        let url = URL(string: "\(baseURL)/models/\(model):\(action)?key=\(apiKey)")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        request.timeoutInterval = 120

        let (data, response) = try await URLSession.shared.data(for: request)

        if let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode != 200 {
            let errorText = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw GeminiError.apiError(statusCode: httpResponse.statusCode, message: errorText)
        }

        return data
    }

    private func extractText(from data: Data) -> String? {
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let candidates = json["candidates"] as? [[String: Any]],
              let first = candidates.first,
              let content = first["content"] as? [String: Any],
              let parts = content["parts"] as? [[String: Any]] else {
            return nil
        }

        // Collect all text parts (skip function calls)
        return parts.compactMap { $0["text"] as? String }.joined()
    }

    /// Extracts function calls AND captures all raw model parts (including thought signatures)
    private func extractFunctionCallsAndModelParts(from data: Data) -> (calls: [FunctionCall], rawModelParts: [[String: Any]]) {
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let candidates = json["candidates"] as? [[String: Any]],
              let first = candidates.first,
              let content = first["content"] as? [String: Any],
              let parts = content["parts"] as? [[String: Any]] else {
            return ([], [])
        }

        var calls: [FunctionCall] = []
        for part in parts {
            if let fc = part["functionCall"] as? [String: Any],
               let name = fc["name"] as? String {
                let args = fc["args"] as? [String: Any] ?? [:]
                calls.append(FunctionCall(name: name, args: args, rawPart: part))
            }
        }

        // Return ALL parts as-is (preserves thoughtSignature, thought parts, etc.)
        return (calls, parts)
    }

    enum GeminiError: LocalizedError {
        case noAPIKey
        case apiError(statusCode: Int, message: String)

        var errorDescription: String? {
            switch self {
            case .noAPIKey:
                return "No API key configured. Go to Settings (Cmd+,) and enter your Gemini API key."
            case .apiError(let code, let message):
                return "Gemini API error (\(code)): \(message)"
            }
        }
    }
}
