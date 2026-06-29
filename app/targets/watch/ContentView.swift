import SwiftUI

struct ContentView: View {
    @EnvironmentObject var store: DoorStore

    var body: some View {
        ScrollView {
            VStack(spacing: 10) {
                StatusCard(store: store)
                ControlButtons(store: store)
                OwnerToggles(store: store)
            }
            .padding(.horizontal, 4)
        }
        .onAppear  { store.startPolling() }
        .onDisappear { store.stopPolling() }
    }
}

// MARK: - Status Card

private struct StatusCard: View {
    @ObservedObject var store: DoorStore

    private var icon: String {
        switch store.doorState {
        case "open":    return "door.sliding.right.hand.open"
        case "closed":  return "door.sliding.right.hand.closed"
        case "opening": return "arrow.up.circle"
        case "closing": return "arrow.down.circle"
        default:        return "questionmark.circle"
        }
    }

    private var label: String {
        let s = store.doorState.capitalized
        if store.doorState == "open", store.openPct > 0 {
            return "\(s) \(Int(store.openPct))%"
        }
        return s
    }

    private var color: Color {
        switch store.doorState {
        case "open":    return .green
        case "closed":  return .secondary
        case "opening": return .yellow
        case "closing": return .orange
        default:        return .gray
        }
    }

    var body: some View {
        VStack(spacing: 4) {
            Image(systemName: icon)
                .font(.system(size: 36))
                .foregroundColor(color)
            Text(label)
                .font(.headline)
            if !store.connected {
                Text("Offline")
                    .font(.caption2)
                    .foregroundColor(.red)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 10)
        .background(Color(white: 0.15))
        .cornerRadius(12)
    }
}

// MARK: - Control Buttons

private struct ControlButtons: View {
    @ObservedObject var store: DoorStore
    @State private var busy = false

    var body: some View {
        HStack(spacing: 6) {
            CommandButton(label: "Open",  color: .green,  disabled: busy) {
                await send("open")
            }
            CommandButton(label: "Stop",  color: .orange, disabled: busy) {
                await send("stop")
            }
            CommandButton(label: "Close", color: .red,    disabled: busy) {
                await send("close")
            }
        }
    }

    private func send(_ cmd: String) async {
        guard !busy else { return }
        busy = true
        await store.sendCommand(cmd)
        busy = false
    }
}

private struct CommandButton: View {
    let label: String
    let color: Color
    let disabled: Bool
    let action: () async -> Void

    var body: some View {
        Button {
            Task { await action() }
        } label: {
            Text(label)
                .font(.system(size: 13, weight: .semibold))
                .frame(maxWidth: .infinity)
                .padding(.vertical, 8)
                .background(disabled ? Color.gray.opacity(0.3) : color.opacity(0.85))
                .cornerRadius(10)
        }
        .buttonStyle(.plain)
        .disabled(disabled)
    }
}

// MARK: - Owner Toggles

private struct OwnerToggles: View {
    @ObservedObject var store: DoorStore

    var body: some View {
        VStack(spacing: 0) {
            OwnerRow(name: "Rita",   available: store.owner1) { on in
                Task { await store.setOwner("owners/owner1", available: on) }
            }
            Divider().background(Color.white.opacity(0.15))
            OwnerRow(name: "Ginger", available: store.owner2) { on in
                Task { await store.setOwner("owners/owner2", available: on) }
            }
        }
        .background(Color(white: 0.15))
        .cornerRadius(12)
    }
}

private struct OwnerRow: View {
    let name: String
    let available: Bool
    let onToggle: (Bool) -> Void

    var body: some View {
        HStack {
            Image(systemName: available ? "person.fill.checkmark" : "person.fill.xmark")
                .foregroundColor(available ? .green : .secondary)
            Text(name)
                .font(.subheadline)
            Spacer()
            Toggle("", isOn: Binding(
                get: { available },
                set: { onToggle($0) }
            ))
            .toggleStyle(SwitchToggleStyle(tint: .green))
            .frame(width: 44)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
    }
}
