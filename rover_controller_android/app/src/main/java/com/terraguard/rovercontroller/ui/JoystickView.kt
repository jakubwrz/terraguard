package com.terraguard.rovercontroller.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlin.math.abs
import kotlin.math.roundToInt
import kotlin.math.sqrt

@Composable
fun JoystickView(
    modifier: Modifier = Modifier,
    onDirectionChanged: (String) -> Unit
) {
    val maxLimitDp = 65.dp
    val deadzoneDp = 20.dp
    
    val density = LocalDensity.current
    val maxLimitPx = with(density) { maxLimitDp.toPx() }
    val deadzonePx = with(density) { deadzoneDp.toPx() }

    var dragOffset by remember { mutableStateOf(Offset.Zero) }
    var lastSentCmd by remember { mutableStateOf("S") }
    var lastSendTime by remember { mutableStateOf(0L) }
    var lastX by remember { mutableStateOf(0) }
    var lastY by remember { mutableStateOf(0) }

    Box(
        modifier = modifier
            .size(190.dp)
            .shadow(20.dp, shape = CircleShape, clip = false)
            .clip(CircleShape)
            .background(Color(0xFF0F1227).copy(alpha = 0.8f))
            .border(2.dp, Color.White.copy(alpha = 0.08f), CircleShape)
            .pointerInput(Unit) {
                detectDragGestures(
                    onDragStart = { },
                    onDragEnd = {
                        dragOffset = Offset.Zero
                        lastX = 0
                        lastY = 0
                        lastSentCmd = "S"
                        onDirectionChanged("JOY:0,0")
                    },
                    onDragCancel = {
                        dragOffset = Offset.Zero
                        lastX = 0
                        lastY = 0
                        lastSentCmd = "S"
                        onDirectionChanged("JOY:0,0")
                    },
                    onDrag = { change, dragAmount ->
                        change.consume()
                        val newOffset = dragOffset + dragAmount
                        val distance = sqrt(newOffset.x * newOffset.x + newOffset.y * newOffset.y)
                        
                        dragOffset = if (distance > maxLimitPx) {
                            Offset(
                                x = (newOffset.x / distance) * maxLimitPx,
                                y = (newOffset.y / distance) * maxLimitPx
                            )
                        } else {
                            newOffset
                        }

                        val now = System.currentTimeMillis()
                        val (curX, curY) = if (distance < deadzonePx) {
                            Pair(0, 0)
                        } else {
                            val normX = (dragOffset.x / maxLimitPx).coerceIn(-1f, 1f)
                            val normY = (-dragOffset.y / maxLimitPx).coerceIn(-1f, 1f)
                            Pair((normX * 100).roundToInt(), (normY * 100).roundToInt())
                        }

                        // Send if significant change (>=5%) or if 60ms elapsed
                        if (abs(curX - lastX) >= 5 || abs(curY - lastY) >= 5 || (now - lastSendTime >= 60 && (curX != lastX || curY != lastY))) {
                            lastX = curX
                            lastY = curY
                            lastSendTime = now
                            val cmd = "JOY:$curX,$curY"
                            lastSentCmd = cmd
                            onDirectionChanged(cmd)
                        }
                    }
                )
            },
        contentAlignment = Alignment.Center
    ) {
        // Direction Labels
        Text(
            text = "FORWARD (F)",
            color = Color.White.copy(alpha = 0.2f),
            fontSize = 9.sp,
            fontWeight = FontWeight.Bold,
            modifier = Modifier
                .align(Alignment.TopCenter)
                .padding(top = 15.dp)
        )
        Text(
            text = "BACKWARD (B)",
            color = Color.White.copy(alpha = 0.2f),
            fontSize = 9.sp,
            fontWeight = FontWeight.Bold,
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .padding(bottom = 15.dp)
        )
        Text(
            text = "LEFT (L)",
            color = Color.White.copy(alpha = 0.2f),
            fontSize = 9.sp,
            fontWeight = FontWeight.Bold,
            modifier = Modifier
                .align(Alignment.CenterStart)
                .padding(start = 15.dp)
        )
        Text(
            text = "RIGHT (R)",
            color = Color.White.copy(alpha = 0.2f),
            fontSize = 9.sp,
            fontWeight = FontWeight.Bold,
            modifier = Modifier
                .align(Alignment.CenterEnd)
                .padding(end = 15.dp)
        )

        // Guide ring
        Canvas(modifier = Modifier.size(140.dp)) {
            drawCircle(
                color = Color.White.copy(alpha = 0.03f),
                radius = size.minDimension / 2,
                style = Stroke(width = 1.dp.toPx())
            )
        }

        // Knob
        Box(
            modifier = Modifier
                .offset { IntOffset(dragOffset.x.roundToInt(), dragOffset.y.roundToInt()) }
                .size(75.dp)
                .shadow(10.dp, shape = CircleShape)
                .background(
                    brush = Brush.radialGradient(
                        colors = listOf(Color(0xFF5A60E0), Color(0xFF2E2781)),
                        radius = 120f
                    ),
                    shape = CircleShape
                )
                .border(1.dp, Color.White.copy(alpha = 0.2f), CircleShape),
            contentAlignment = Alignment.Center
        ) {
            Box(
                modifier = Modifier
                    .size(25.dp)
                    .background(Color.White.copy(alpha = 0.07f), CircleShape)
                    .border(1.dp, Color.White.copy(alpha = 0.1f), CircleShape)
            )
        }
    }
}
