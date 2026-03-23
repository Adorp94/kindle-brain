import Foundation

/// Manages the Python API server as a child process.
@MainActor
class ServerManager: ObservableObject {
    static let shared = ServerManager()

    @Published var isRunning = false
    @Published var statusMessage = "Starting server..."

    private var process: Process?
    private let projectRoot: String

    // Hardcoded project root — where kindle/ lives
    private static let defaultProjectRoot = "/Users/adolfo/Documents/testing/kindle"

    init() {
        self.projectRoot = Self.defaultProjectRoot
    }

    func start() {
        guard process == nil else {
            isRunning = true
            return
        }

        // Check if server is already running on the port
        Task {
            if await isServerReachable() {
                isRunning = true
                statusMessage = "Server connected"
                return
            }

            await launchServer()
        }
    }

    private func launchServer() async {
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        proc.arguments = ["python3", "-m", "uvicorn", "scripts.api_server:app",
                          "--host", "127.0.0.1", "--port", "8765"]
        proc.currentDirectoryURL = URL(fileURLWithPath: projectRoot)

        // Capture stderr for debugging
        let errPipe = Pipe()
        proc.standardOutput = FileHandle.nullDevice
        proc.standardError = errPipe

        proc.terminationHandler = { [weak self] _ in
            Task { @MainActor in
                self?.isRunning = false
                self?.statusMessage = "Server stopped"
                self?.process = nil
            }
        }

        do {
            try proc.run()
            process = proc
            statusMessage = "Server starting..."

            // Wait for server to be ready
            for _ in 0..<20 {
                try await Task.sleep(nanoseconds: 500_000_000)
                if await isServerReachable() {
                    isRunning = true
                    statusMessage = "Server running"
                    return
                }
            }

            statusMessage = "Server may not have started correctly"
        } catch {
            statusMessage = "Failed to start: \(error.localizedDescription)"
        }
    }

    private func isServerReachable() async -> Bool {
        guard let url = URL(string: "http://127.0.0.1:8765/stats") else { return false }
        do {
            let (_, response) = try await URLSession.shared.data(from: url)
            return (response as? HTTPURLResponse)?.statusCode == 200
        } catch {
            return false
        }
    }

    func stop() {
        if let proc = process, proc.isRunning {
            proc.terminate()
        }
        process = nil
        isRunning = false
        statusMessage = "Server stopped"
    }

    func stopSync() {
        // For use in app termination
        process?.terminate()
    }
}
