import Foundation
import Network

struct DiscoveredDevice: Identifiable, Hashable {
    let name: String
    let endpoint: NWEndpoint
    var lastSeen: Date = Date()
    
    // Stable ID based on service name
    var id: String { name }
    
    func hash(into hasher: inout Hasher) {
        hasher.combine(name)
    }
    
    static func == (lhs: DiscoveredDevice, rhs: DiscoveredDevice) -> Bool {
        lhs.name == rhs.name
    }
    
    // Extract IP/Port if possible for UI
    var connectionString: String {
        if case let .hostPort(host, port) = endpoint {
            return "\(host):\(port)"
        }
        return "READY"
    }
}

class DiscoveryManager: ObservableObject {
    @Published var discoveredDevices: [DiscoveredDevice] = []
    
    private var browser: NWBrowser?
    private let serviceType = "_nothing-share._tcp"
    private let domain = "local."
    
    init() {
        startBrowsing()
    }
    
    func startBrowsing() {
        let parameters = NWParameters()
        parameters.includePeerToPeer = true
        
        let descriptor = NWBrowser.Descriptor.bonjour(type: serviceType, domain: domain)
        browser = NWBrowser(for: descriptor, using: .main)
        
        browser?.stateUpdateHandler = { state in
            switch state {
            case .ready:
                print("Discovery Manager: Ready and browsing...")
            case .failed(let error):
                print("Discovery Manager: Failed with error: \(error)")
            default:
                break
            }
        }
        
        browser?.browseResultsChangedHandler = { [weak self] results, changes in
            guard let self = self else { return }
            
            DispatchQueue.main.async {
                // Efficiently update the list without full rebuild
                var currentDevices = self.discoveredDevices
                
                for change in changes {
                    switch change {
                    case .added(let result):
                        if case let .bonjourService(name, _, _, _) = result.endpoint {
                            let newDevice = DiscoveredDevice(name: name, endpoint: result.endpoint)
                            if !currentDevices.contains(newDevice) {
                                currentDevices.append(newDevice)
                                print("Discovery Manager: Added \(name)")
                            }
                        }
                    case .removed(let result):
                        if case let .bonjourService(name, _, _, _) = result.endpoint {
                            currentDevices.removeAll { $0.name == name }
                            print("Discovery Manager: Removed \(name)")
                        }
                    default:
                        break
                    }
                }
                
                // Final sync with all results to ensure consistency
                let allActiveNames = results.compactMap { result -> String? in
                    if case let .bonjourService(name, _, _, _) = result.endpoint { return name }
                    return nil
                }
                currentDevices = currentDevices.filter { allActiveNames.contains($0.name) }
                
                if self.discoveredDevices != currentDevices {
                    self.discoveredDevices = currentDevices
                }
            }
        }
        
        browser?.start(queue: .main)
    }
    
    func stopBrowsing() {
        browser?.cancel()
        browser = nil
    }
}
