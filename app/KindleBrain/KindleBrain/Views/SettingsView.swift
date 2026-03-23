import SwiftUI

struct SettingsView: View {
    @AppStorage("apiServerURL") private var apiServerURL = "http://127.0.0.1:8765"
    @AppStorage("dataDirectory") private var dataDirectory = "~/.kindle-brain"

    var body: some View {
        Form {
            Section("API Server") {
                TextField("Server URL", text: $apiServerURL)
                    .textFieldStyle(.roundedBorder)
            }
            Section("Data") {
                LabeledContent("Data Directory", value: dataDirectory)
                    .textSelection(.enabled)
            }
            Section("About") {
                LabeledContent("Version", value: "0.1.0")
                Link("Documentation", destination: URL(string: "https://github.com/Adorp94/kindle-brain")!)
            }
        }
        .formStyle(.grouped)
        .frame(width: 450, height: 250)
    }
}
