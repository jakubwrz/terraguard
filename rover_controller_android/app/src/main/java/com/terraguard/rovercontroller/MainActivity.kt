package com.terraguard.rovercontroller

import android.Manifest
import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanResult
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.ArrowForward
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowLeft
import androidx.compose.material.icons.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.app.ActivityCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import com.terraguard.rovercontroller.ui.JoystickView
import java.util.UUID

class MainActivity : ComponentActivity() {

    private val tag = "RoverMainActivity"

    // BLE UUID Constants
    private val serviceUuid: UUID = UUID.fromString("a07498ca-ad5b-474e-940d-16f1fbe7e8cd")
    private val charUuid: UUID    = UUID.fromString("51ff12bb-3ed8-46e5-b4f9-d64e2fec021b")

    private val bluetoothAdapter: BluetoothAdapter? by lazy {
        val bluetoothManager = getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager
        bluetoothManager.adapter
    }

    private var bluetoothGatt: BluetoothGatt? = null
    private var cmdCharacteristic: BluetoothGattCharacteristic? = null

    // Compose Observables
    private val logs = mutableStateListOf<String>()
    private var isConnected by mutableStateOf(false)
    private var isConnecting by mutableStateOf(false)
    private var isScanning by mutableStateOf(false)
    private val scanResults = mutableStateListOf<BluetoothDevice>()

    private val handler = Handler(Looper.getMainLooper())

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        
        // Immersive Fullscreen Mode (Hide Status Bar & Navigation Bar)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        val insetsController = WindowCompat.getInsetsController(window, window.decorView)
        insetsController.hide(WindowInsetsCompat.Type.systemBars())
        insetsController.systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE

        log("System starting in FULLSCREEN LANDSCAPE mode. Requesting BLE Permissions...")
        checkAndRequestPermissions()

        setContent {
            MaterialTheme(
                colorScheme = darkColorScheme(
                    primary = Color(0xFF4F46E5),
                    secondary = Color(0xFF6366F1),
                    background = Color(0xFF070913),
                    surface = Color(0xFF121629)
                )
            ) {
                DashboardScreen()
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        disconnectGatt()
    }

    private fun log(message: String) {
        val time = java.text.SimpleDateFormat("HH:mm:ss", java.util.Locale.getDefault()).format(java.util.Date())
        logs.add(0, "[$time] $message")
        Log.i(tag, message)
    }

    // --- PERMISSION NEGOTIATOR ---
    private fun checkAndRequestPermissions() {
        val permissions = mutableListOf(
            Manifest.permission.ACCESS_FINE_LOCATION,
            Manifest.permission.ACCESS_COARSE_LOCATION
        )
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            permissions.add(Manifest.permission.BLUETOOTH_SCAN)
            permissions.add(Manifest.permission.BLUETOOTH_CONNECT)
        }
        
        requestPermissionLauncher.launch(permissions.toTypedArray())
    }

    private val requestPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { results ->
        val granted = results.all { it.value }
        if (granted) {
            log("All Bluetooth and Location permissions granted.")
        } else {
            log("WARNING: Permissions denied. BLE scanning disabled. Mock mode active.")
            Toast.makeText(this, "Bluetooth permissions are required for BLE features", Toast.LENGTH_LONG).show()
        }
    }

    private fun hasPermission(permission: String): Boolean {
        return ActivityCompat.checkSelfPermission(this, permission) == PackageManager.PERMISSION_GRANTED
    }

    private fun checkBlePermissions(): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            hasPermission(Manifest.permission.BLUETOOTH_SCAN) && hasPermission(Manifest.permission.BLUETOOTH_CONNECT)
        } else {
            hasPermission(Manifest.permission.ACCESS_FINE_LOCATION)
        }
    }

    // --- BLE CORE IMPLEMENTATION ---
    @SuppressLint("MissingPermission")
    private fun startScan() {
        if (isScanning) return
        if (bluetoothAdapter == null || !bluetoothAdapter!!.isEnabled) {
            log("Error: Bluetooth adapter is disabled or unavailable.")
            return
        }
        if (!checkBlePermissions()) {
            log("Error: Missing BLE permissions.")
            return
        }

        scanResults.clear()
        isScanning = true
        log("Scanning for TerraGuard Rover...")

        val scanner = bluetoothAdapter!!.bluetoothLeScanner
        
        handler.postDelayed({
            if (isScanning) {
                scanner.stopScan(scanCallback)
                isScanning = false
                log("Scan timed out.")
            }
        }, 5000)

        scanner.startScan(scanCallback)
    }

    private val scanCallback = object : ScanCallback() {
        @SuppressLint("MissingPermission")
        override fun onScanResult(callbackType: Int, result: ScanResult?) {
            result?.device?.let { device ->
                val name = device.name ?: ""
                if (name.uppercase().contains("TERRAGUARD") && !scanResults.any { it.address == device.address }) {
                    scanResults.add(device)
                    log("Found device: ${device.name} [${device.address}] -> Auto-connecting...")
                    scanner.stopScan(this)
                    isScanning = false
                    connectToDevice(device)
                }
            }
        }

        override fun onScanFailed(errorCode: Int) {
            log("BLE scan failed with error code: $errorCode")
            isScanning = false
        }
    }

    @SuppressLint("MissingPermission")
    private fun connectToDevice(device: BluetoothDevice) {
        if (!checkBlePermissions()) return
        
        isConnecting = true
        log("Connecting to ${device.name ?: "Rover"} [${device.address}]...")

        disconnectGatt()

        bluetoothGatt = device.connectGatt(this, false, gattCallback)
    }

    @SuppressLint("MissingPermission")
    private fun disconnectGatt() {
        bluetoothGatt?.let { gatt ->
            log("Disconnecting from GATT Server...")
            gatt.disconnect()
            gatt.close()
            bluetoothGatt = null
        }
        isConnected = false
        isConnecting = false
        cmdCharacteristic = null
    }

    private val gattCallback = object : BluetoothGattCallback() {
        @SuppressLint("MissingPermission")
        override fun onConnectionStateChange(gatt: BluetoothGatt?, status: Int, newState: Int) {
            if (newState == BluetoothProfile.STATE_CONNECTED) {
                log("Connected to GATT. Discovering services...")
                gatt?.discoverServices()
            } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                handler.post {
                    isConnected = false
                    isConnecting = false
                    cmdCharacteristic = null
                    log("Disconnected from Rover.")
                }
            }
        }

        @SuppressLint("MissingPermission")
        override fun onServicesDiscovered(gatt: BluetoothGatt?, status: Int) {
            if (status == BluetoothGatt.GATT_SUCCESS && gatt != null) {
                val service = gatt.getService(serviceUuid)
                if (service != null) {
                    val characteristic = service.getCharacteristic(charUuid)
                    if (characteristic != null) {
                        gatt.setCharacteristicNotification(characteristic, true)
                        val cccd = characteristic.getDescriptor(UUID.fromString("00002902-0000-1000-8000-00805f9b34fb"))
                        if (cccd != null) {
                            cccd.value = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
                            gatt.writeDescriptor(cccd)
                        }
                        handler.post {
                            isConnected = true
                            isConnecting = false
                            cmdCharacteristic = characteristic
                            log("GATT Connected! Control channel linked successfully.")
                        }
                    } else {
                        log("Error: Target characteristic UUID not found in service.")
                        gatt.disconnect()
                    }
                } else {
                    log("Error: Target service UUID not found on device.")
                    gatt.disconnect()
                }
            } else {
                log("Service discovery failed with status $status")
            }
        }

        @Deprecated("Deprecated in Java")
        override fun onCharacteristicChanged(gatt: BluetoothGatt?, characteristic: BluetoothGattCharacteristic?) {
            val bytes = characteristic?.value ?: return
            val msg = String(bytes, Charsets.UTF_8)
            handler.post {
                log(msg)
            }
        }

        override fun onCharacteristicChanged(gatt: BluetoothGatt, characteristic: BluetoothGattCharacteristic, value: ByteArray) {
            val msg = String(value, Charsets.UTF_8)
            handler.post {
                log(msg)
            }
        }
    }

    @SuppressLint("MissingPermission")
    private fun sendCommand(cmd: String) {
        val characteristic = cmdCharacteristic
        val gatt = bluetoothGatt
        
        if (characteristic == null || gatt == null) {
            log("MOCK Send: \"$cmd\" (BLE Not Connected)")
            return
        }

        if (!checkBlePermissions()) return

        characteristic.value = cmd.toByteArray(Charsets.UTF_8)
        characteristic.writeType = BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT
        val success = gatt.writeCharacteristic(characteristic)
        if (success) {
            log("Sent: $cmd")
        } else {
            log("Transmission failed for command: $cmd")
        }
    }

    // --- JETPACK COMPOSE LANDSCAPE UI ---
    @Composable
    private fun DashboardScreen() {
        // Current Screen State: "MAIN_MENU", "TEACH", "WAYPOINTS", "DRIVE"
        var currentScreen by remember { mutableStateOf("MAIN_MENU") }

        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(
                    brush = Brush.radialGradient(
                        colors = listOf(Color(0xFF151A3A), Color(0xFF070913)),
                        radius = 1600f
                    )
                )
                .padding(12.dp)
        ) {
            Column(modifier = Modifier.fillMaxSize()) {
                // Top Header Bar
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(bottom = 8.dp),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        if (currentScreen != "MAIN_MENU") {
                            IconButton(
                                onClick = {
                                    currentScreen = "MAIN_MENU"
                                    sendCommand("MODE_IDLE")
                                },
                                modifier = Modifier
                                    .background(Color.White.copy(alpha = 0.08f), CircleShape)
                                    .size(36.dp)
                            ) {
                                Icon(
                                    imageVector = Icons.Default.ArrowBack,
                                    contentDescription = "Back to Main Menu",
                                    tint = Color.White
                                )
                            }
                            Spacer(modifier = Modifier.width(10.dp))
                        }

                        Text(
                            text = when (currentScreen) {
                                "TEACH" -> "📷 TEACH MODE (Manual Driving & Risk Photos)"
                                "WAYPOINTS" -> "📍 WAYPOINTS MODE (Drive & Path Recording)"
                                "DRIVE" -> "🤖 DRIVE MODE (Autonomous Navigation)"
                                else -> "🛡️ TerraGuard Rover Control Center"
                            },
                            color = Color.White,
                            fontWeight = FontWeight.Bold,
                            fontSize = 18.sp
                        )
                    }

                    Row(verticalAlignment = Alignment.CenterVertically) {
                        StatusIndicator(isConnected)
                        
                        if (!isConnected) {
                            Button(
                                onClick = { startScan() },
                                enabled = !isScanning,
                                colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF6366F1)),
                                shape = RoundedCornerShape(10.dp),
                                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 4.dp)
                            ) {
                                if (isScanning || isConnecting) {
                                    CircularProgressIndicator(
                                        modifier = Modifier.size(14.dp),
                                        strokeWidth = 2.dp,
                                        color = Color.White
                                    )
                                    Spacer(modifier = Modifier.width(6.dp))
                                    Text(if (isConnecting) "Connecting..." else "Scanning...", fontSize = 12.sp)
                                } else {
                                    Icon(Icons.Default.Refresh, contentDescription = null, modifier = Modifier.size(14.dp))
                                    Spacer(modifier = Modifier.width(6.dp))
                                    Text("Connect", fontSize = 12.sp, fontWeight = FontWeight.Bold)
                                }
                            }
                        } else {
                            Button(
                                onClick = { disconnectGatt() },
                                colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFEF4444)),
                                shape = RoundedCornerShape(10.dp),
                                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 4.dp)
                            ) {
                                Text("Disconnect", fontSize = 12.sp)
                            }
                        }
                    }
                }

                // Available BLE Device Picker (If scanning)
                if (!isConnected && scanResults.isNotEmpty()) {
                    LazyRow(
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(bottom = 8.dp)
                    ) {
                        items(scanResults) { device ->
                            @SuppressLint("MissingPermission")
                            val name = device.name ?: "Unknown Rover"
                            Card(
                                colors = CardDefaults.cardColors(containerColor = Color.White.copy(alpha = 0.08f)),
                                shape = RoundedCornerShape(8.dp),
                                modifier = Modifier.clickable { connectToDevice(device) }
                            ) {
                                Text(
                                    text = "Connect to: $name",
                                    fontSize = 12.sp,
                                    fontWeight = FontWeight.SemiBold,
                                    color = Color.White,
                                    modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp)
                                )
                            }
                        }
                    }
                }

                // Main Screen Content Switching
                Box(modifier = Modifier.weight(1f)) {
                    when (currentScreen) {
                        "MAIN_MENU" -> MainSelectionMenu(
                            onSelectTeach = {
                                currentScreen = "TEACH"
                                sendCommand("MODE_TEACH")
                            },
                            onSelectWaypoints = {
                                currentScreen = "WAYPOINTS"
                                sendCommand("MODE_WAYPOINTS")
                            },
                            onSelectDrive = {
                                currentScreen = "DRIVE"
                                sendCommand("MODE_DRIVE")
                            }
                        )
                        "TEACH" -> ManualDriveScreen(modeLabel = "TEACH", isRecordingWaypoints = false)
                        "WAYPOINTS" -> ManualDriveScreen(modeLabel = "WAYPOINTS", isRecordingWaypoints = true)
                        "DRIVE" -> AutonomousDriveScreen(onEmergencyStop = {
                            currentScreen = "MAIN_MENU"
                            sendCommand("MODE_IDLE")
                        })
                    }
                }
            }
        }
    }

    // --- MAIN SELECTION MENU (App Startup Screen) ---
    @Composable
    private fun MainSelectionMenu(
        onSelectTeach: () -> Unit,
        onSelectWaypoints: () -> Unit,
        onSelectDrive: () -> Unit
    ) {
        Column(
            modifier = Modifier.fillMaxSize(),
            verticalArrangement = Arrangement.SpaceBetween
        ) {
            Text(
                text = "SELECT OPERATING MODE TO START:",
                fontSize = 12.sp,
                fontWeight = FontWeight.Bold,
                color = Color.Gray,
                letterSpacing = 1.2.sp
            )

            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f)
                    .padding(vertical = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                // Card 1: TEACH MODE
                MainMenuCard(
                    title = "📷 TEACH MODE",
                    subtitle = "Manual Drive & Risk Photos",
                    badgeColor = Color(0xFF6366F1),
                    onClick = onSelectTeach,
                    modifier = Modifier.weight(1f)
                )

                // Card 2: WAYPOINTS MODE
                MainMenuCard(
                    title = "📍 WAYPOINTS",
                    subtitle = "Drive & Record Path",
                    badgeColor = Color(0xFFF59E0B),
                    onClick = onSelectWaypoints,
                    modifier = Modifier.weight(1f)
                )

                // Card 3: DRIVE MODE
                MainMenuCard(
                    title = "🤖 DRIVE MODE",
                    subtitle = "Autonomous Path Replay",
                    badgeColor = Color(0xFF10B981),
                    onClick = onSelectDrive,
                    modifier = Modifier.weight(1f)
                )
            }

            // Compact Log Console
            Box(
                modifier = Modifier
                    .height(65.dp)
                    .fillMaxWidth()
                    .background(Color.Black.copy(alpha = 0.4f), shape = RoundedCornerShape(10.dp))
                    .border(1.dp, Color.White.copy(alpha = 0.05f), shape = RoundedCornerShape(10.dp))
                    .padding(8.dp)
            ) {
                LazyColumn(modifier = Modifier.fillMaxSize()) {
                    items(logs) { logMsg ->
                        Text(
                            text = logMsg,
                            fontFamily = FontFamily.Monospace,
                            fontSize = 10.sp,
                            color = Color(0xFF4ADE80)
                        )
                    }
                }
            }
        }
    }

    @Composable
    private fun MainMenuCard(
        title: String,
        subtitle: String,
        badgeColor: Color,
        onClick: () -> Unit,
        modifier: Modifier = Modifier
    ) {
        Box(
            modifier = modifier
                .fillMaxHeight()
                .shadow(8.dp, shape = RoundedCornerShape(16.dp))
                .clip(RoundedCornerShape(16.dp))
                .background(Color(0xFF121629).copy(alpha = 0.85f))
                .border(1.5.dp, badgeColor.copy(alpha = 0.4f), RoundedCornerShape(16.dp))
                .clickable { onClick() }
                .padding(16.dp)
        ) {
            Column(
                modifier = Modifier.fillMaxSize(),
                verticalArrangement = Arrangement.SpaceBetween,
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Surface(
                        color = badgeColor.copy(alpha = 0.2f),
                        shape = RoundedCornerShape(8.dp)
                    ) {
                        Text(
                            text = title,
                            fontWeight = FontWeight.Bold,
                            fontSize = 16.sp,
                            color = Color.White,
                            modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp)
                        )
                    }

                    Spacer(modifier = Modifier.height(10.dp))

                    Text(
                        text = subtitle,
                        fontSize = 13.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = badgeColor
                    )
                }

                Button(
                    onClick = onClick,
                    colors = ButtonDefaults.buttonColors(containerColor = badgeColor),
                    shape = RoundedCornerShape(12.dp),
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(44.dp)
                ) {
                    Text("START MODE", fontWeight = FontWeight.Bold, fontSize = 13.sp)
                }
            }
        }
    }

    // --- MANUAL DRIVE SCREEN (Used for both TEACH and WAYPOINTS) ---
    @Composable
    private fun ManualDriveScreen(modeLabel: String, isRecordingWaypoints: Boolean) {
        Row(
            modifier = Modifier.fillMaxSize(),
            horizontalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            // Column 1: Joystick & Arrow Pads
            GlassPanel(modifier = Modifier.weight(1.1f)) {
                Column(
                    modifier = Modifier.fillMaxSize(),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.SpaceBetween
                ) {
                    Text(
                        text = "MANUAL ROBOT DRIVING",
                        fontSize = 11.sp,
                        fontWeight = FontWeight.Bold,
                        color = Color.Gray
                    )

                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .weight(1f),
                        contentAlignment = Alignment.Center
                    ) {
                        JoystickView(
                            modifier = Modifier.size(175.dp),
                            onDirectionChanged = { dir -> sendCommand(dir) }
                        )
                    }

                    Surface(
                        color = if (isRecordingWaypoints) Color(0xFFF59E0B).copy(alpha = 0.15f) else Color(0xFF6366F1).copy(alpha = 0.15f),
                        shape = RoundedCornerShape(6.dp),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Text(
                            text = if (isRecordingWaypoints) "📍 Recording path breadcrumbs..." else "📷 Teach Mode: Free manual drive",
                            fontSize = 10.sp,
                            fontWeight = FontWeight.SemiBold,
                            color = Color.White,
                            modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp)
                        )
                    }
                }
            }

            // Column 2: Camera Servo Panner & Risk Training Photo Buttons
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                // Camera Panner Card
                GlassPanel(modifier = Modifier.weight(1f)) {
                    Column(
                        modifier = Modifier.fillMaxSize(),
                        verticalArrangement = Arrangement.SpaceBetween,
                        horizontalAlignment = Alignment.CenterHorizontally
                    ) {
                        Text(
                            text = "CAMERA SERVO PANNING",
                            fontSize = 11.sp,
                            fontWeight = FontWeight.Bold,
                            color = Color.Gray
                        )

                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(6.dp)
                        ) {
                            PannerButton(label = "Left (-60°)", icon = Icons.Default.ArrowBack, onClick = { sendCommand("CAM_L") }, modifier = Modifier.weight(1f))
                            PannerButton(label = "Center (0°)", icon = Icons.Default.Refresh, onClick = { sendCommand("CAM_C") }, modifier = Modifier.weight(1f))
                            PannerButton(label = "Right (+60°)", icon = Icons.Default.ArrowForward, onClick = { sendCommand("CAM_R") }, modifier = Modifier.weight(1f))
                        }

                        // Servo Angle Slider
                        var sliderPos by remember { mutableStateOf(0f) }
                        Column(modifier = Modifier.fillMaxWidth()) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween
                            ) {
                                Text("Angle Adjustment:", fontSize = 10.sp, color = Color.LightGray)
                                Text("${sliderPos.toInt()}°", fontSize = 10.sp, fontWeight = FontWeight.Bold, color = Color(0xFF6366F1))
                            }
                            Slider(
                                value = sliderPos,
                                onValueChange = { sliderPos = it },
                                onValueChangeFinished = {
                                    sendCommand("SERVO:${sliderPos.toInt()}")
                                },
                                valueRange = -60f..60f,
                                steps = 12
                            )
                        }
                    }
                }

                // Risk Training Photo Card
                GlassPanel(modifier = Modifier.weight(1f)) {
                    Column(
                        modifier = Modifier.fillMaxSize(),
                        verticalArrangement = Arrangement.SpaceBetween,
                        horizontalAlignment = Alignment.CenterHorizontally
                    ) {
                        Text(
                            text = "TAKE RISK TRAINING PHOTO",
                            fontSize = 11.sp,
                            fontWeight = FontWeight.Bold,
                            color = Color.Gray
                        )

                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            RiskButton(label = "Low Risk", cmd = "P_LOW", colors = listOf(Color(0xFF10B981), Color(0xFF059669)), onClick = { sendCommand("P_LOW") }, modifier = Modifier.weight(1f))
                            RiskButton(label = "Med Risk", cmd = "P_MED", colors = listOf(Color(0xFFF59E0B), Color(0xFFD97706)), onClick = { sendCommand("P_MED") }, modifier = Modifier.weight(1f))
                            RiskButton(label = "High Risk", cmd = "P_HIGH", colors = listOf(Color(0xFFEF4444), Color(0xFFDC2626)), onClick = { sendCommand("P_HIGH") }, modifier = Modifier.weight(1f))
                        }
                    }
                }
            }
        }
    }

    // --- AUTONOMOUS DRIVE SCREEN ---
    @Composable
    private fun AutonomousDriveScreen(onEmergencyStop: () -> Unit) {
        GlassPanel(modifier = Modifier.fillMaxSize()) {
            Column(
                modifier = Modifier.fillMaxSize(),
                verticalArrangement = Arrangement.Center,
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Icon(
                    imageVector = Icons.Default.PlayArrow,
                    contentDescription = null,
                    tint = Color(0xFF10B981),
                    modifier = Modifier.size(56.dp)
                )
                Spacer(modifier = Modifier.height(12.dp))
                Text(
                    text = "AUTONOMOUS NAVIGATION ACTIVE",
                    fontWeight = FontWeight.Bold,
                    fontSize = 18.sp,
                    color = Color.White
                )
                Text(
                    text = "Rover is executing path playback over recorded waypoints.",
                    fontSize = 12.sp,
                    color = Color.Gray
                )
                Spacer(modifier = Modifier.height(20.dp))
                Button(
                    onClick = onEmergencyStop,
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFEF4444)),
                    shape = RoundedCornerShape(12.dp),
                    modifier = Modifier
                        .fillMaxWidth(0.5f)
                        .height(48.dp)
                ) {
                    Text("EMERGENCY STOP (IDLE)", fontWeight = FontWeight.Bold, fontSize = 14.sp)
                }
            }
        }
    }

    @Composable
    private fun ArrowPadButton(
        icon: ImageVector,
        cmd: String,
        label: String,
        color: Color = Color(0xFF6366F1)
    ) {
        Box(
            modifier = Modifier
                .size(38.dp)
                .clip(RoundedCornerShape(8.dp))
                .background(color.copy(alpha = 0.25f))
                .border(1.dp, color, RoundedCornerShape(8.dp))
                .clickable { sendCommand(cmd) },
            contentAlignment = Alignment.Center
        ) {
            Icon(icon, contentDescription = label, tint = Color.White, modifier = Modifier.size(22.dp))
        }
    }

    @SuppressLint("MissingPermission")
    private fun connectedDeviceName(): String {
        return bluetoothGatt?.device?.name ?: "Connected Rover"
    }

    @Composable
    private fun StatusIndicator(isConnected: Boolean) {
        val indicatorColor by animateColorAsState(
            if (isConnected) Color(0xFF10B981) else Color(0xFFEF4444),
            label = "IndicatorColor"
        )
        Box(
            modifier = Modifier
                .padding(end = 12.dp)
                .border(1.dp, Color.White.copy(alpha = 0.08f), RoundedCornerShape(20.dp))
                .background(Color.White.copy(alpha = 0.04f), RoundedCornerShape(20.dp))
                .padding(horizontal = 10.dp, vertical = 4.dp)
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(6.dp)
            ) {
                Box(
                    modifier = Modifier
                        .size(8.dp)
                        .background(indicatorColor, shape = CircleShape)
                )
                Text(
                    text = if (isConnected) "Connected" else "Disconnected",
                    fontSize = 11.sp,
                    fontWeight = FontWeight.SemiBold
                )
            }
        }
    }

    @Composable
    private fun GlassPanel(
        modifier: Modifier = Modifier,
        content: @Composable BoxScope.() -> Unit
    ) {
        Box(
            modifier = modifier
                .fillMaxWidth()
                .background(Color(0xFF121629).copy(alpha = 0.6f), shape = RoundedCornerShape(16.dp))
                .border(1.dp, Color.White.copy(alpha = 0.06f), shape = RoundedCornerShape(16.dp))
                .padding(12.dp),
            content = content
        )
    }

    @Composable
    private fun PannerButton(
        label: String,
        icon: ImageVector,
        onClick: () -> Unit,
        modifier: Modifier = Modifier
    ) {
        OutlinedButton(
            onClick = onClick,
            shape = RoundedCornerShape(8.dp),
            border = androidx.compose.foundation.BorderStroke(1.dp, Color.White.copy(alpha = 0.1f)),
            colors = ButtonDefaults.outlinedButtonColors(
                containerColor = Color.White.copy(alpha = 0.03f)
            ),
            contentPadding = PaddingValues(vertical = 8.dp),
            modifier = modifier
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(4.dp)
            ) {
                Icon(icon, contentDescription = null, tint = Color(0xFF6366F1), modifier = Modifier.size(14.dp))
                Text(label, fontSize = 11.sp, fontWeight = FontWeight.SemiBold, color = Color.White)
            }
        }
    }

    @Composable
    private fun RiskButton(
        label: String,
        cmd: String,
        colors: List<Color>,
        onClick: () -> Unit,
        modifier: Modifier = Modifier
    ) {
        Box(
            modifier = modifier
                .shadow(4.dp, shape = RoundedCornerShape(10.dp))
                .clip(RoundedCornerShape(10.dp))
                .background(Brush.horizontalGradient(colors))
                .clickable { onClick() }
                .padding(vertical = 10.dp),
            contentAlignment = Alignment.Center
        ) {
            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center
            ) {
                Text(
                    text = label,
                    fontWeight = FontWeight.Bold,
                    color = Color.White,
                    fontSize = 12.sp
                )
                Text(
                    text = cmd,
                    fontSize = 8.sp,
                    color = Color.White.copy(alpha = 0.7f)
                )
            }
        }
    }
}
