#!/usr/bin/python3
import os
import time
import docker
import subprocess
from flask_cors import CORS
from nvitop import Device
from flask import Flask, jsonify, render_template


app = Flask(__name__)
CORS(app, supports_credentials=True)


pid_cache = {}
all_devices = Device.all()
gpu_number = len(all_devices)
docker_client = docker.from_env()
if os.path.exists('/sys/fs/cgroup/cgroup.controllers'):
    cgroup_version = 'v2'
else:
    cgroup_version = 'v1'


def pid2container(pid):
    global cgroup_version, docker_client
    # v1
    # $ cat /proc/[PID]/cgroup
    # 12:devices:/docker/955227b75e228e25f22e1fea884d293a28bfe417be6ce39d99d05bf88c09ffe3
    # 11:cpuset:/docker/955227b75e228e25f22e1fea884d293a28bfe417be6ce39d99d05bf88c09ffe3
    # 10:hugetlb:/docker/955227b75e228e25f22e1fea884d293a28bfe417be6ce39d99d05bf88c09ffe3
    # 9:blkio:/docker/955227b75e228e25f22e1fea884d293a28bfe417be6ce39d99d05bf88c09ffe3
    # 8:perf_event:/docker/955227b75e228e25f22e1fea884d293a28bfe417be6ce39d99d05bf88c09ffe3
    # 7:net_cls,net_prio:/docker/955227b75e228e25f22e1fea884d293a28bfe417be6ce39d99d05bf88c09ffe3
    # 6:rdma:/docker/955227b75e228e25f22e1fea884d293a28bfe417be6ce39d99d05bf88c09ffe3
    # 5:memory:/docker/955227b75e228e25f22e1fea884d293a28bfe417be6ce39d99d05bf88c09ffe3
    # 4:freezer:/docker/955227b75e228e25f22e1fea884d293a28bfe417be6ce39d99d05bf88c09ffe3
    # 3:cpu,cpuacct:/docker/955227b75e228e25f22e1fea884d293a28bfe417be6ce39d99d05bf88c09ffe3
    # 2:pids:/docker/955227b75e228e25f22e1fea884d293a28bfe417be6ce39d99d05bf88c09ffe3
    # 1:name=systemd:/docker/955227b75e228e25f22e1fea884d293a28bfe417be6ce39d99d05bf88c09ffe3
    # 0::/docker/955227b75e228e25f22e1fea884d293a28bfe417be6ce39d99d05bf88c09ffe3
    #
    # v2
    # /proc/[PID]/cgroup
    # 0::/system.slice/docker-fe9730ee647b428d03df83e0b93137eb56d14053d9c141d2696c534b1c9db76a.scope
    try:
        with open(f"/proc/{pid}/cgroup", 'r') as f:
            cgroup_content = f.read()
    except:
        return None

    container_id = None
    if cgroup_version == 'v1':
        for line in cgroup_content.split("\n"):
            if 'docker' in line:
                container_id = line.split("/")[-1]
                break
    else:
        for line in cgroup_content.split("\n"):
            if 'docker' in line:
                container_id = line.split("docker-")[-1].split(".")[0]
                break

    if container_id:
        return docker_client.containers.get(container_id).name
    return None


def get_process_list():
    """获取进程列表"""
    global pid_cache
    processes = []
    new_pid_cache = {}

    for device in all_devices:
        device_processes = device.processes()
        for process in device_processes.values():
            if process.type == "G":  # 不处理图形化进程，例如 Xorg
                continue
            try:                     # 捕获所有可能的异常，主要是 host.ZombieProcess
                process_snapshot = process.as_snapshot()
            except:
                continue
            pid = process_snapshot.pid
            pid_cache_item = pid_cache.get(pid)
            if pid_cache_item:
                type = pid_cache_item['type']
                username = pid_cache_item['username']
            else:
                container_name = pid2container(pid)
                if container_name:
                    type = "container"
                    username = container_name
                else:
                    type = "host"
                    username = process_snapshot.username
            new_pid_cache[pid] = {
                "type": type,
                "username": username
            }

            process = {
                "device_idx": device.index,
                "gpu_memory": process_snapshot.gpu_memory // (1024 * 1024),  # bytes to MiB
                "gpu_memory_human": process_snapshot.gpu_memory_human,
                "gpu_memory_percent": process_snapshot.gpu_memory_percent,
                "gpu_sm_utilization": process_snapshot.gpu_sm_utilization,

                "pid": process_snapshot.pid,
                "name": process_snapshot.name,
                "command": process_snapshot.command,
                "cpu_percent": process_snapshot.cpu_percent,
                "host_memory": process_snapshot.host_memory // (1024 * 1024),  # bytes to MiB
                "host_memory_human": process_snapshot.host_memory_human,
                "memory_percent": process_snapshot.memory_percent,
                "running_time_in_seconds": process_snapshot.running_time_in_seconds,
                "running_time_human": process_snapshot.running_time_human,

                "type": type,
                "username": username,
            }
            processes.append(process)

    pid_cache = new_pid_cache
    return processes


def get_gpu_status():
    """获取显卡状态：温度、显存占用、显卡占用、功耗等"""
    status_list = []
    for device in all_devices:
        status_list.append({
            "memory_used": device.memory_used() // (1024 * 1024), # bytes to MiB
            "gpu_utilization": device.gpu_utilization(),
            "temperature": device.temperature(),
            "power_usage": device.power_usage() / 1000.0,  # mW to W
        })
    data = {
        "timestamp": int(round(time.time())) * 1000,
        "status": status_list
    }
    return data


@app.route("/")
@app.route("/index.html")
def api_index_html():
    return render_template("index.html")


@app.route("/process.html")
def api_process_html():
    return render_template("process.html")


@app.route("/process")
def api_process():
    return jsonify(get_process_list())


@app.route("/status")
def api_status():
    return jsonify(get_gpu_status())


@app.route("/gpu-number")
def api_gpu_number():
    return str(gpu_number)


if __name__ == "__main__":
    app.run()
