package com.nothing.airshare

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.util.Log
import java.net.InetAddress

class NsdHelper(private val context: Context, private val listener: NsdListener) {
    private val nsdManager = context.getSystemService(Context.NSD_SERVICE) as NsdManager
    private val serviceType = "_nothing-share._tcp."
    private var registrationListener: NsdManager.RegistrationListener? = null
    private var discoveryListener: NsdManager.DiscoveryListener? = null

    interface NsdListener {
        fun onDeviceDiscovered(name: String, host: InetAddress, port: Int)
        fun onDeviceRemoved(name: String)
    }

    fun registerService(port: Int) {
        val serviceInfo = NsdServiceInfo().apply {
            serviceName = "Nothing Phone Share"
            serviceType = this@NsdHelper.serviceType
            setPort(port)
        }

        registrationListener = object : NsdManager.RegistrationListener {
            override fun onServiceRegistered(nsdServiceInfo: NsdServiceInfo) {
                Log.d("NSD", "Service registered successfully: ${nsdServiceInfo.serviceName}")
            }

            override fun onRegistrationFailed(serviceInfo: NsdServiceInfo, errorCode: Int) {
                Log.e("NSD", "Service registration failed: $errorCode")
            }

            override fun onServiceUnregistered(arg0: NsdServiceInfo) {}
            override fun onUnregistrationFailed(serviceInfo: NsdServiceInfo, errorCode: Int) {}
        }

        nsdManager.registerService(serviceInfo, NsdManager.PROTOCOL_DNS_SD, registrationListener)
    }

    fun discoverServices() {
        discoveryListener = object : NsdManager.DiscoveryListener {
            override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) {
                Log.e("NSD", "Discovery start failed: $errorCode")
                nsdManager.stopServiceDiscovery(this)
            }

            override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) {
                Log.e("NSD", "Discovery stop failed: $errorCode")
                nsdManager.stopServiceDiscovery(this)
            }

            override fun onDiscoveryStarted(serviceType: String) {
                Log.d("NSD", "Discovery started")
            }

            override fun onDiscoveryStopped(serviceType: String) {
                Log.d("NSD", "Discovery stopped")
            }

            override fun onServiceFound(serviceInfo: NsdServiceInfo) {
                Log.d("NSD", "Service found: ${serviceInfo.serviceName}")
                if (serviceInfo.serviceType == serviceType) {
                    if (serviceInfo.serviceName != "Nothing Phone Share") {
                        resolveService(serviceInfo)
                    }
                }
            }

            override fun onServiceLost(serviceInfo: NsdServiceInfo) {
                Log.d("NSD", "Service lost: ${serviceInfo.serviceName}")
                listener.onDeviceRemoved(serviceInfo.serviceName)
            }
        }

        nsdManager.discoverServices(serviceType, NsdManager.PROTOCOL_DNS_SD, discoveryListener)
    }

    private fun resolveService(serviceInfo: NsdServiceInfo) {
        val resolveListener = object : NsdManager.ResolveListener {
            override fun onResolveFailed(serviceInfo: NsdServiceInfo, errorCode: Int) {
                Log.e("NSD", "Resolve failed: $errorCode")
            }

            override fun onServiceResolved(resolvedServiceInfo: NsdServiceInfo) {
                Log.d("NSD", "Resolve succeeded: ${resolvedServiceInfo.serviceName} at ${resolvedServiceInfo.host}:${resolvedServiceInfo.port}")
                listener.onDeviceDiscovered(
                    resolvedServiceInfo.serviceName,
                    resolvedServiceInfo.host,
                    resolvedServiceInfo.port
                )
            }
        }
        
        nsdManager.resolveService(serviceInfo, resolveListener)
    }

    fun stop() {
        try {
            registrationListener?.let { nsdManager.unregisterService(it) }
        } catch (e: Exception) {
            Log.e("NSD", "Unregister failed: ${e.message}")
        }
        try {
            discoveryListener?.let { nsdManager.stopServiceDiscovery(it) }
        } catch (e: Exception) {
            Log.e("NSD", "Stop discovery failed: ${e.message}")
        }
    }
}
